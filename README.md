# Bot de señales de trading (MEXC + Telegram)

Bot que analiza futuros perpetuos en MEXC, avisa por Telegram cuando detecta una señal y,
solo si tú lo confirmas con un botón, abre la operación con stop loss, take profit y trailing stop.

## Variables de entorno (o Secret Files en Render)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `TEL_TOKEN` (o `TELEGRAM_TOKEN`, `TOKEN`, `TELKEY`) | Sí | Token del bot de Telegram |
| `MEXC_API_KEY` / `MEXC_SECRET_KEY` | Sí, para operar | Credenciales de MEXC |
| `TELEGRAM_CHAT_ID` | Recomendada | ID de Telegram del **único** usuario autorizado. Por defecto usa el ID que ya estaba en el código |
| `MODO_DEMO` | No | `true` = no se envía ninguna orden real; todo se simula con el precio de mercado |
| `MODO_MARGEN` | No | `isolated` (por defecto) o `cross` |

## Cómo funciona la protección de cada operación

- Stop loss 4 % y take profit 8 % se envían a MEXC con la orden **y además** los vigila el bot cada 20 s.
- El trailing stop (4 %) lo gestiona el bot: solo sube (en largos) o solo baja (en cortos) y, si el precio lo toca,
  cierra la posición a mercado con una orden `reduceOnly`.
- Si el bot está apagado o reiniciando, solo protegen los SL/TP guardados en MEXC.
- El límite de pérdida diaria suma las **pérdidas reales** de las operaciones cerradas.
- Las órdenes en seguimiento se guardan en `estado_bot.json`. En el plan gratuito de Render el disco es
  efímero y ese archivo se pierde al reiniciar: revisa tus posiciones abiertas en MEXC después de cada reinicio.

## Recomendación

Antes de operar con dinero real, arranca con `MODO_DEMO=true` unos días y comprueba que las señales y los
cierres simulados se comportan como esperas.
