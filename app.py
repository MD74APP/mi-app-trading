import ccxt
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from flask import Flask, render_template, request

app = Flask(__name__)

# Activos a analizar (solo criptomonedas)
activos = {
    'BTC/USDT': 'criptos',
    'ETH/USDT': 'criptos',
    'BNB/USDT': 'criptos',
    'XRP/USDT': 'criptos'
}

# Obtener datos (velas de 5 minutos)
def obtener_datos(simbolo):
    exchange = ccxt.binance()
    datos = exchange.fetch_ohlcv(simbolo, timeframe='5m', limit=100)  # 100 velas de 5 minutos
    datos = pd.DataFrame(datos, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    datos['timestamp'] = pd.to_datetime(datos['timestamp'], unit='ms')
    return datos

# Calcular volatilidad promedio (para ajustar porcentajes dinámicamente)
def calcular_volatilidad(df):
    df['rango'] = (df['high'] - df['low']) / df['close'] * 100
    volatilidad_promedio = df['rango'].tail(72).mean()  # Últimas 72 velas (6 horas, 5m)
    return max(volatilidad_promedio, 1.5)  # Mínimo 1.5% para evitar tiempos irreales

# Calcular indicadores (EMA_9, EMA_50, RSI_14, MACD)
def calcular_indicadores(df):
    df['EMA_9'] = EMAIndicator(df['close'], window=9).ema_indicator()  # EMA rápida
    df['EMA_50'] = EMAIndicator(df['close'], window=50).ema_indicator()  # EMA más lenta
    df['RSI'] = RSIIndicator(df['close'], window=14).rsi()  # RSI estándar
    macd = MACD(df['close'])  # MACD estándar (12, 26, 9)
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    return df

# Generar orden y OCO
def generar_orden(df, simbolo):
    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2]
    
    # Calcular volatilidad
    volatilidad = calcular_volatilidad(df)
    porcentaje_ganancia = 1.0  # Cambiado de 1.2% a 1.0%
    porcentaje_stop = max(2.5, min(4, volatilidad * 1.5))  # Entre 2.5% y 4%, ajustado por volatilidad
    porcentaje_limit_stop = 0.5  # Fijo en 0.5% por debajo del stop
    
    # Calcular horizonte temporal estimado (en horas)
    tiempo_estimado = round((1.0 / volatilidad) * 6, 1) if volatilidad > 0 else 4.0  # Default 4 horas si volatilidad es 0
    
    # Tendencia
    tendencia = "Alcista" if ultimo['EMA_9'] > ultimo['EMA_50'] and ultimo['MACD'] > ultimo['MACD_Signal'] else "Bajista"
    
    # Precio actual con formato según el par
    decimals = 4 if 'XRP' in simbolo else 2
    precio_actual = round(ultimo['close'], decimals)
    
    # Orden inicial y parámetros OCO
    if tendencia == "Alcista" and ultimo['RSI'] < 75:  # Umbral ajustado a 75
        precio_compra = precio_actual
        precio_venta = round(precio_compra * (1 + porcentaje_ganancia / 100), decimals)  # Ganancia ajustada
        ganancia_calculada = ((precio_venta - precio_compra) / precio_compra) * 100
        probabilidad = 70 if ultimo['MACD'] > 0 else 60
        orden = f"Compra {simbolo} a {precio_compra}. Vende a {precio_venta}."
        
        # Parámetros OCO
        oco_limit = precio_venta
        oco_stop = round(precio_compra * (1 - porcentaje_stop / 100), decimals)
        oco_limit_stop = round(oco_stop * (1 - porcentaje_limit_stop / 100), decimals)
        oco = {
            'limit_order': f"Orden Limit de Venta: {oco_limit} USDT",
            'stop': f"Stop: {oco_stop} USDT",
            'limit_stop': f"Limit en Stop-Limit: {oco_limit_stop} USDT"
        }
    elif tendencia == "Bajista" and ultimo['RSI'] > 25:  # Umbral ajustado a 25
        precio_venta = precio_actual
        precio_compra = round(precio_venta * (1 - porcentaje_ganancia / 100), decimals)  # Ganancia en corto
        ganancia_calculada = ((precio_venta - precio_compra) / precio_venta) * 100
        probabilidad = 70 if ultimo['MACD'] < 0 else 60
        orden = f"Vende {simbolo} a {precio_venta}. Compra a {precio_compra}."
        
        # Parámetros OCO para posición corta
        oco_limit = precio_compra
        oco_stop = round(precio_venta * (1 + porcentaje_stop / 100), decimals)
        oco_limit_stop = round(oco_stop * (1 + porcentaje_limit_stop / 100), decimals)
        oco = {
            'limit_order': f"Orden Limit de Compra: {oco_limit} USDT",
            'stop': f"Stop: {oco_stop} USDT",
            'limit_stop': f"Limit en Stop-Limit: {oco_limit_stop} USDT"
        }
    else:
        orden = "Sin señal clara. Espera. (Condiciones técnicas no cumplidas)"
        probabilidad = 0
        ganancia_calculada = 0
        tiempo_estimado = 0
        oco = None
    
    return {
        'simbolo': simbolo,
        'tendencia': tendencia,
        'orden': orden,
        'probabilidad': probabilidad,
        'ganancia': ganancia_calculada,
        'tiempo_estimado': f"Tiempo estimado: {tiempo_estimado} horas" if tiempo_estimado > 0 else "",
        'oco': oco
    }

# Ruta principal
@app.route('/', methods=['GET', 'POST'])
def index():
    resultado = None
    if request.method == 'POST':
        simbolo = request.form['activo']
        datos = obtener_datos(simbolo)
        if datos is not None and not datos.empty:
            datos = calcular_indicadores(datos)
            resultado = generar_orden(datos, simbolo)
    return render_template('index.html', activos=activos.keys(), resultado=resultado)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
