from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import logging, os, ssl, socket
import certifi
import aiomqtt
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import CallbackQueryHandler


# Configuración de entorno
token = os.environ["TB_TOKEN"]
autorizados = [int(x) for x in os.environ["TB_AUTORIZADOS"].split(',')]
MQTT_BROKER = os.environ.get("MQTT_BROKER")  # Nombre de servicio Docker o IP
MQTT_PORT = int(os.environ.get("MQTT_PORT"))  # Puerto TLS
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")
TOPICO_BASE = os.environ.get("TOPICO")  # ID del dispositivo

# Contexto SSL para MQTTS usando certifi
ssl_context = ssl.create_default_context(cafile=certifi.where())
ssl_context.check_hostname = True
ssl_context.verify_mode = ssl.CERT_REQUIRED

logging.basicConfig(format='%(asctime)s - TelegramBot - %(levelname)s - %(message)s', level=logging.INFO)
logging.info(f"Inicializando bot. Broker MQTT: {MQTT_BROKER}:{MQTT_PORT} con TLS certificado")

async def sin_autorizacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Intento de conexión de: {update.message.from_user.id}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔒 No autorizado.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    nombre = user.first_name or ""
    apellido = user.last_name or ""
    
    mensaje = (
        f"👋 ¡Bienvenido, {nombre} {apellido}!\n\n"
        "🤖 Este bot te permite controlar remotamente un *termostato IoT* mediante comandos y botones interactivos.\n"
        "Podés configurar el setpoint de temperatura, el período de muestreo, el modo de funcionamiento, y controlar el relé.\n\n"
        "Usá el comando /menu para comenzar. 📋"
    )
    
    await context.bot.send_message(
        chat_id=update.message.chat.id,
        text=mensaje,
        parse_mode="Markdown"
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Seleccioná una opción:", reply_markup=await generar_teclado_principal())


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("esperando"):
        context.user_data["esperando"] = None
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text="❌ Operación cancelada.",
                                       reply_markup=await generar_teclado_principal())
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text="ℹ️ No hay ninguna operación activa.",
                                       reply_markup=await generar_teclado_principal())
                                       
async def generar_teclado_principal():
    keyboard = [
        [InlineKeyboardButton("🛠 Setpoint", callback_data="menu_setpoint")],
        [InlineKeyboardButton("⏱ Periodo", callback_data="menu_periodo")],
        [InlineKeyboardButton("⚙️ Modo", callback_data="menu_modo")],
        [InlineKeyboardButton("🔌 Relé", callback_data="menu_rele")],
        [InlineKeyboardButton("💡 Destello", callback_data="menu_destello")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_operacion")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_setpoint":
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Ingresar valor", callback_data="ingresar_setpoint")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")]
        ])
        await query.edit_message_text("🔧 Setpoint", reply_markup=reply_markup)

    elif data == "ingresar_setpoint":
        context.user_data["esperando"] = "setpoint"
        await query.edit_message_text("📥 Ingresá el valor del setpoint (ej. 23.5):")
        
    elif data == "menu_periodo":
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Ingresar valor", callback_data="ingresar_periodo")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")]
        ])
        await query.edit_message_text("⏱ Periodo", reply_markup=reply_markup)

    elif data == "ingresar_periodo":
        context.user_data["esperando"] = "periodo"
        await query.edit_message_text("📥 Ingresá el valor del periodo en segundos (ej. 60):")

    elif data == "menu_modo":
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Manual (0)", callback_data="modo_0"),
            InlineKeyboardButton("Automático (1)", callback_data="modo_1")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")]
        ])
        await query.edit_message_text("⚙️ Seleccioná el modo:", reply_markup=reply_markup)

    elif data == "modo_0" or data == "modo_1":
        valor = "0" if data == "modo_0" else "1"
        texto = "Modo Manual" if valor == "0" else "Modo Automático"
        topic = f"{TOPICO_BASE}/modo"
        context.user_data["modo_actual"] = valor  # Guardamos el estado del modo
        await query.edit_message_text(f"🔄 {texto}")
        await publish_mqtt(topic, valor.encode(), update, context)

    elif data == "menu_rele":
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("OFF (0)", callback_data="rele_0"),
            InlineKeyboardButton("ON (1)", callback_data="rele_1")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")]
        ])
        await query.edit_message_text("🔌 Control del relé:", reply_markup=reply_markup)

    elif data == "rele_0" or data == "rele_1":
        valor = "0" if data == "rele_0" else "1"
        estado = "OFF" if valor == "0" else "ON"
        topic = f"{TOPICO_BASE}/rele"
        await query.edit_message_text(f"🔄 Relé: {estado}")
        await publish_mqtt(topic, valor.encode(), update, context)

    elif data == "menu_destello":
        topic = f"{TOPICO_BASE}/destello"
        await query.edit_message_text("💡 Destello LED enviado.")
        await publish_mqtt(topic, b"1", update, context)

    elif data == "cancelar_operacion":
        context.user_data["esperando"] = None
        await query.edit_message_text("❌ Operación cancelada.")
    
    elif data == "cancelar":
        context.user_data["esperando"] = None
        await query.edit_message_text("🚫 Acción cancelada. Volvé al menú con /menu")



async def capturar_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entrada = update.message.text.strip()

    esperando = context.user_data.get("esperando")
    if not esperando:
        await update.message.reply_text("❓ No entiendo ese mensaje. Usá /menu para comenzar.")
        return

    if entrada.lower() == "/cancelar":
        context.user_data["esperando"] = None
        await update.message.reply_text("❌ Operación cancelada.",
                                        reply_markup=await generar_teclado_principal())
        return
    esperando = context.user_data.get("esperando")

    if esperando == "setpoint":
        topic = f"{TOPICO_BASE}/setpoint"
        await update.message.reply_text(f"✅ Setpoint recibido: {entrada}")
        await publish_mqtt(topic, entrada.encode(), update, context)
        modo_actual = context.user_data.get("modo_actual")
        if modo_actual == "0":
            await update.message.reply_text(
                "⚠️ El sistema está en *modo manual*. El setpoint fue actualizado pero no tendrá efecto hasta que se active el modo automático.",
                parse_mode="Markdown"
            )
    
    elif esperando == "periodo":
        topic = f"{TOPICO_BASE}/periodo"
        await update.message.reply_text(f"✅ Periodo recibido: {entrada} segundos")
        await publish_mqtt(topic, entrada.encode(), update, context)

    else:
        await update.message.reply_text("❓ No entiendo ese mensaje. Usá /menu para comenzar.")

    context.user_data["esperando"] = None


async def acercade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "ℹ️ *Acerca del Bot*\n\n"
        "Este bot te permite controlar un termostato IoT a través de comandos y botones interactivos.\n\n"
        "✅ Funciones disponibles:\n"
        "• Ver estado actual del sistema\n"
        "• Ajustar el *setpoint* de temperatura\n"
        "• Configurar el *período* de muestreo\n"
        "• Cambiar el *modo de funcionamiento* (Manual/Automático)\n"
        "• Encender o apagar el *relé* manualmente\n\n"
        "🔗 La comunicación se realiza mediante el protocolo MQTT.\n"
        "Usá /menu para comenzar a interactuar."
    )
    await context.bot.send_message(
        chat_id=update.message.chat.id,
        text=texto,
        parse_mode="Markdown"
    )

async def publish_mqtt(topic: str, payload: bytes, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Verificación DNS
    try:
        ip = socket.gethostbyname(MQTT_BROKER)
        logging.info(f"Resolución DNS: {MQTT_BROKER} → {ip}")
    except socket.gaierror:
        await context.bot.send_message(update.message.chat.id, text=f"❌ Error DNS: {MQTT_BROKER} no se resuelve.")
        return False

    try:
        # Conexión y publicación en un solo bloque async
        async with aiomqtt.Client(
            MQTT_BROKER,
            port=MQTT_PORT,
            username=MQTT_USER,
            password=MQTT_PASS,
            tls_context=ssl_context
        ) as client:
            logging.info(f"Conectado a {MQTT_BROKER}:{MQTT_PORT} con TLS certificado")
            logging.info(f"Publicando en {topic}: {payload}")
            await client.publish(topic, payload, qos=1)
            logging.info("Publicación exitosa")
            return True
    except aiomqtt.MqttError as e:
        logging.error(f"Error MQTT: {e}")
        await context.bot.send_message(update.message.chat.id, text=f"❌ Falló MQTT: {e}\nVerifica broker, puerto y certificados.")
        return False

# Handlers de comandos
async def setpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await context.bot.send_message(update.message.chat.id, text="Uso: /setpoint <valor>")
    valor = context.args[0]
    topic = f"{TOPICO_BASE}/setpoint"
    await context.bot.send_message(update.message.chat.id, text=f"🔄 Setpoint: {valor}")
    await publish_mqtt(topic, valor.encode(), update, context)

async def periodo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await context.bot.send_message(update.message.chat.id, text="Uso: /periodo <segundos>")
    valor = context.args[0]
    topic = f"{TOPICO_BASE}/periodo"
    await context.bot.send_message(update.message.chat.id, text=f"🔄 Periodo: {valor}s")
    await publish_mqtt(topic, valor.encode(), update, context)

async def modo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] not in ["0", "1"]:
        return await context.bot.send_message(update.message.chat.id, text="Uso: /modo <0|1>")
    valor = context.args[0]
    texto = "Modo Automático" if valor == "1" else "Modo Manual"
    topic = f"{TOPICO_BASE}/modo"
    await context.bot.send_message(update.message.chat.id, text=f"🔄 {texto}")
    await publish_mqtt(topic, valor.encode(), update, context)

async def rele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] not in ["0", "1"]:
        return await context.bot.send_message(update.message.chat.id, text="Uso: /rele <0|1>")
    valor = context.args[0]
    estado = "ON" if valor == "1" else "OFF"
    topic = f"{TOPICO_BASE}/rele"
    await context.bot.send_message(update.message.chat.id, text=f"🔄 Relé: {estado}")
    await publish_mqtt(topic, valor.encode(), update, context)

async def destello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = f"{TOPICO_BASE}/destello"
    await context.bot.send_message(update.message.chat.id, text="🔄 Destello LED")
    await publish_mqtt(topic, b"1", update, context)

# Main
def main():
    application = Application.builder().token(token).build()
    # Filtro de autorizados
    application.add_handler(MessageHandler(~filters.User(autorizados), sin_autorizacion))
    # Comandos
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('acercade', acercade))
    application.add_handler(CommandHandler('menu', menu))
    application.add_handler(CommandHandler('cancelar', cancelar))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(autorizados), capturar_input))
    application.run_polling()

if __name__ == '__main__':
    try:
        print("✅ Bot iniciado. Presiona Ctrl+C para detenerlo.")
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido por el usuario (Ctrl+C).")
    except Exception as e:
        print(f"⚠️ Se produjo un error inesperado: {e}")
    finally:
        print("🔒 Finalizando procesos... Limpieza completada.")
