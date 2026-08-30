#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT DE SEÑALES DE TRADING - KUCOIN FUTUROS
Usa analisis.py para indicadores y señales automáticas
"""

import os
import sys
import logging
from datetime import datetime

from analisis import (
    analizar_par, escanear_todos, formatear_mensaje,
    PARES, obtener_velas, obtener_ticker
)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN", "TU_TOKEN_AQUI")

ALERTA_INTERVALO_MIN = 5

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
def teclado_principal():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Señales", callback_data="menu_señales"),
         InlineKeyboardButton("Análisis Técnico", callback_data="menu_analisis")],
        [InlineKeyboardButton("Alertas Automáticas", callback_data="menu_alertas"),
         InlineKeyboardButton("Configuración", callback_data="menu_config")],
    ])


def teclado_pares():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("BTC", callback_data="par_BTC"),
         InlineKeyboardButton("ETH", callback_data="par_ETH")],
        [InlineKeyboardButton("SOL", callback_data="par_SOL"),
         InlineKeyboardButton("XRP", callback_data="par_XRP")],
        [InlineKeyboardButton("BNB", callback_data="par_BNB")],
        [InlineKeyboardButton("Volver", callback_data="volver")],
    ])


def teclado_accion():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Actualizar", callback_data="actualizar"),
         InlineKeyboardButton("Análisis Completo", callback_data="analisis_full")],
        [InlineKeyboardButton("Volver", callback_data="volver")],
    ])


def teclado_alertas():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Activar Alertas", callback_data="alertas_on"),
         InlineKeyboardButton("Detener Alertas", callback_data="alertas_off")],
        [InlineKeyboardButton("Escanear Ahora", callback_data="escanear")],
        [InlineKeyboardButton("Volver", callback_data="volver")],
    ])
        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["chat_id"] = update.effective_chat.id
    
    texto = ("""Bot de Señales - KuCoin Futuros
    
Hola """ + user.first_name + """!

Este bot analiza futuros perpetuos en KuCoin y avisa cuando hay oportunidades de entrada y salida.

Capital: 10 USDT
Mercado: Futuros Perpetuos
Temporalidad: 15 minutos

Indicadores: RSI, EMA(9/21), MACD, Bollinger, Estocástico, ATR, Volumen

Apalancamiento: Calculado automático según volatilidad (3x a 10x)

Comandos:
/start - Menu principal
/operar - Elegir par para operar
/señal [PAR] - Señal rápida
/analisis - Análisis multi-temporalidad
/config - Ver configuración

No es asesoría financiera. Opera bajo tu propio riesgo.""")
    
    await update.message.reply_text(texto, reply_markup=teclado_principal())


async def operar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["chat_id"] = update.effective_chat.id
    context.user_data["timeframe"] = "15min"
    
    await update.message.reply_text(
        "Elige un par para operar:",
        reply_markup=teclado_pares()
                             )
async def señal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].upper() in PARES:
        par = args[0].upper()
        tf = context.user_data.get("timeframe", "15min")
        await enviar_analisis(update, context, par, tf)
    else:
        await update.message.reply_text(
            "Elige un par:",
            reply_markup=teclado_pares()
        )


async def analisis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Análisis Técnico Avanzado\nElige un par:",
        reply_markup=teclado_pares()
    )


async def config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tf = context.user_data.get("timeframe", "15min")
    alertas = "Activas" if context.user_data.get("alertas_activas") else "Inactivas"
    
    texto = ("""Configuración Actual
    
Capital base: 10 USDT
Temporalidad: """ + tf + """
Alertas: """ + alertas + """
Pares: BTC, ETH, SOL, XRP, BNB

Indicadores:
  RSI(14): Sobrecompra 70 / Sobreventa 30
  EMA: 9 y 21 períodos
  MACD: (12, 26, 9)
  Bollinger: 20 períodos, 2σ
  Estocástico: 14 períodos
  ATR: 14 períodos

Apalancamiento:
  Volatilidad < 0.3% -> 10x
  Volatilidad 0.3-0.6% -> 7x
  Volatilidad 0.6-1.0% -> 5x
  Volatilidad > 1.0% -> 3x

Gestión de riesgo:
  SL: 2x ATR
  TP: 3x ATR
  Máximo riesgo: 2% por operación""")
    
    await update.message.reply_text(texto)
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "menu_señales":
        await query.edit_message_text(
            "Señales de Trading\nElige un par:",
            reply_markup=teclado_pares()
        )
    
    elif data == "menu_analisis":
        await query.edit_message_text(
            "Análisis Técnico Avanzado\nElige un par:",
            reply_markup=teclado_pares()
        )
    
    elif data == "menu_alertas":
        await query.edit_message_text(
            "Alertas Automáticas\n\n"
            "El bot revisará el mercado cada 5 minutos "
            "y te avisará solo cuando haya señales fuertes.",
            reply_markup=teclado_alertas()
        )
    
    elif data == "menu_config":
        await config(update, context)
    
    elif data.startswith("par_"):
        par = data.split("_")[1]
        context.user_data["par_seleccionado"] = par
        tf = context.user_data.get("timeframe", "15min")
        
        msg = await query.edit_message_text(
            "Analizando " + par + "-USDT en " + tf + "...",
        )
        
        resultado = analizar_par(par, tf)
        if resultado:
            mensaje = formatear_mensaje(resultado)
            await msg.edit_text(
                mensaje,
                reply_markup=teclado_accion(),
                parse_mode="HTML"
            )
        else:
            await msg.edit_text(
                "Error obteniendo datos de " + par,
                reply_markup=teclado_pares()
            )
    
    elif data == "actualizar":
        par = context.user_data.get("par_seleccionado", "BTC")
        tf = context.user_data.get("timeframe", "15min")
        
        msg = await query.edit_message_text(
            "Actualizando " + par + "-USDT...",
        )
        
        resultado = analizar_par(par, tf)
        if resultado:
            mensaje = formatear_mensaje(resultado)
            await msg.edit_text(
                mensaje,
                reply_markup=teclado_accion(),
                parse_mode="HTML"
            )
    
    elif data == "analisis_full":
        par = context.user_data.get("par_seleccionado", "BTC")
        
        msg = await query.edit_message_text(
            "Analizando " + par + " en múltiples temporalidades...",
        )
        
        r_15m = analizar_par(par, "15min")
        r_1h = analizar_par(par, "1hour")
        
        if r_15m and r_1h:
            texto = ("Análisis Multi-Temporalidad - " + par + "\n"
                     "━━━━━━━━━━━━━━━━━━━━\n\n"
                     "15 minutos:\n"
                     "  Señal: " + r_15m['direccion'] + " " + r_15m['señal'] +
                     " (" + str(r_15m['confianza']) + "%)\n"
                     "  RSI: " + str(r_15m['rsi']) +
                     " | Apalancamiento: " + str(r_15m['apalancamiento']) + "x\n\n"
                     "1 Hora:\n"
                     "  Señal: " + r_1h['direccion'] + " " + r_1h['señal'] +
                     " (" + str(r_1h['confianza']) + "%)\n"
                     "  RSI: " + str(r_1h['rsi']) +
                     " | Apalancamiento: " + str(r_1h['apalancamiento']) + "x\n\n"
                     "Recomendación:\n")
            
            if r_15m['señal'] == r_1h['señal'] and r_15m['señal'] != "NEUTRAL":
                apal = min(r_15m['apalancamiento'], r_1h['apalancamiento'])
                texto += ("ALTA CONFIANZA - Ambas coinciden en " +
                          r_15m['señal'] + "\n"
                          "Apalancamiento: " + str(apal) + "x")
            elif r_1h['señal'] != "NEUTRAL":
                texto += ("MEDIA CONFIANZA - 1H indica " + r_1h['señal'] +
                          "\nEsperar confirmación en 15min.")
            else:
                texto += "SIN SEÑAL CLARA - NO OPERAR"
            
            await msg.edit_text(
                texto,
                reply_markup=teclado_accion()
            )
        else:
            await msg.edit_text(
                "Error en el análisis.",
                reply_markup=teclado_pares()
    )
        elif data == "alertas_on":
        context.user_data["alertas_activas"] = True
        chat_id = update.effective_chat.id
        
        job_queue = context.application.job_queue
        current_jobs = job_queue.get_jobs_by_name("alertas_" + str(chat_id))
        for job in current_jobs:
            job.schedule_removal()
        
        job_queue.run_repeating(
            job_alerta_automatica,
            interval=ALERTA_INTERVALO_MIN * 60,
            first=10,
            chat_id=chat_id,
            name="alertas_" + str(chat_id)
        )
        
        await query.edit_message_text(
            "Alertas activadas\n\n"
            "El bot revisará el mercado cada 5 minutos "
            "y te enviará señales solo con confianza > 70%.",
            reply_markup=teclado_alertas()
        )
    
    elif data == "alertas_off":
        context.user_data["alertas_activas"] = False
        chat_id = update.effective_chat.id
        
        job_queue = context.application.job_queue
        current_jobs = job_queue.get_jobs_by_name("alertas_" + str(chat_id))
        for job in current_jobs:
            job.schedule_removal()
        
        await query.edit_message_text(
            "Alertas detenidas",
            reply_markup=teclado_alertas()
        )
    
    elif data == "escanear":
        msg = await query.edit_message_text(
            "Escaneando todos los pares...",
        )
        
        resultados = escanear_todos("15min")
        
        if resultados:
            texto = "OPORTUNIDADES DETECTADAS\n━━━━━━━━━━━━━━━━━━━━\n\n"
            for r in resultados:
                texto += (r['direccion'] + " " + r['par'] +
                          " - " + r['señal'] +
                          " (" + str(r['confianza']) + "%)\n"
                          "Precio: $" + str(r['precio']) +
                          " | Apalancamiento: " + str(r['apalancamiento']) + "x\n\n")
            
            texto += "\nUsa /señal [PAR] para ver análisis completo."
            await msg.edit_text(
                texto,
                reply_markup=teclado_alertas()
            )
        else:
            await msg.edit_text(
                "Sin oportunidades claras\n\n"
                "Ningún par muestra señal fuerte ahora.\n"
                "El bot te avisará automáticamente cuando aparezca una.",
                reply_markup=teclado_alertas()
            )
    
    elif data == "volver":
        await query.edit_message_text(
            "Bot de Señales - KuCoin Futuros",
            reply_markup=teclado_principal()
        )


async def job_alerta_automatica(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    
    logger.info("Revisando mercado para chat " + str(chat_id))
    
    resultados = escanear_todos("15min")
    
    for r in resultados:
        if r["confianza"] >= 70:
            mensaje = formatear_mensaje(r)
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=mensaje,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error("Error enviando alerta: " + str(e))
    async def enviar_analisis(update, context, par, tf):
    msg = await update.message.reply_text(
        "Analizando " + par + "-USDT en " + tf + "...",
    )
    
    resultado = analizar_par(par, tf)
    if resultado:
        mensaje = formatear_mensaje(resultado)
        await msg.edit_text(
            mensaje,
            reply_markup=teclado_accion(),
            parse_mode="HTML"
        )
    else:
        await msg.edit_text(
            "No se pudieron obtener datos de " + par,
            reply_markup=teclado_pares()
        )


def main():
    if TOKEN == "TU_TOKEN_AQUI":
        print("ERROR: Configura tu BOT_TOKEN")
        print("Opcion 1: export BOT_TOKEN='tu_token'")
        print("Opcion 2: Edita la variable TOKEN en el codigo")
        sys.exit(1)
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("operar", operar))
    application.add_handler(CommandHandler("señal", señal))
    application.add_handler(CommandHandler("analisis", analisis_cmd))
    application.add_handler(CommandHandler("config", config))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    print("Bot iniciado!")
    print("Comandos: /start /operar /señal /analisis /config")
    print("Alertas automaticas: activables desde el menu")
    print("Presiona Ctrl+C para detener.\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
