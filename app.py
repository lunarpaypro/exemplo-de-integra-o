import logging
import sqlite3
import requests
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 📌 Configurações
BOT_TOKEN = '6745407467:'
LUNARPAY_CLIENT_ID = 'X8nHSaH3358r1yHbMUnYQwzP9PC8OCSmeCPlGyMZCu7hcUZympA6UyU5Ss7iZqGqVhDq4c5zicDEpqVMA5HgmB15nDQVZZcdfACq'
LUNARPAY_SECRET_ID = 'hes3Wa7O9kR7XkKSo4HdF7cY9R6dBkwUR2TNQQMcElB5N1jtPCHs5un5qlpxSoN22H5iTYqBCjpKtW3sm4vx8KWiDOkvpEDxErCF'
LUNARPAY_BASE_URL = 'https://lunarpay.pro/pay/api/v1'  # ou sandbox se preferir

# 📌 Banco de dados simples
conn = sqlite3.connect('usuarios.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        user_id INTEGER PRIMARY KEY,
        saldo REAL DEFAULT 0
    )
''')
conn.commit()

# 📌 Logging
logging.basicConfig(level=logging.INFO)

# 📌 Obter token de acesso LunarPay
def obter_token_lunarpay():
    url = f"{LUNARPAY_BASE_URL}/authentication/token"
    payload = {'client_id': LUNARPAY_CLIENT_ID, 'secret_id': LUNARPAY_SECRET_ID}
    headers = {'accept': 'application/json', 'content-type': 'application/json'}
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        logging.info("Token LunarPay obtido com sucesso.")
        return response.json()['data']['access_token']
    else:
        logging.error(f"Erro ao obter token: {response.text}")
        return None

# 📌 Criar pagamento LunarPay
def criar_pagamento_lunarpay(valor, custom_id):
    token = obter_token_lunarpay()
    if not token:
        return None, None
    url = f"{LUNARPAY_BASE_URL}/payment/create"
    payload = {
        'amount': f"{valor:.2f}",
        'currency': 'BRL',
        'return_url': 'http://localhost/success',
        'cancel_url': 'http://localhost/cancel',
        'custom': custom_id
    }
    headers = {'Authorization': f'Bearer {token}', 'accept': 'application/json', 'content-type': 'application/json'}
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200 and response.json()['type'] == 'success':
        logging.info("Pagamento criado com sucesso.")
        return response.json()['data']['payment_url'], response.json()['data']['token']
    else:
        logging.error(f"Erro ao criar pagamento: {response.text}")
        return None, None

# 📌 Verificar status do pagamento (usando token)
def verificar_pagamento_lunarpay(payment_token):
    token = obter_token_lunarpay()
    if not token:
        return False
    url = f"{LUNARPAY_BASE_URL}/payment/status/{payment_token}"
    headers = {'Authorization': f'Bearer {token}', 'accept': 'application/json'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200 and response.json()['type'] == 'success':
        logging.info(f"Status da transação: {response.json()['data']}")
        return True  # Pagamento confirmado
    else:
        logging.warning(f"Status não confirmado: {response.text}")
        return False

# 📌 Atualizar saldo do usuário
def atualizar_saldo(user_id, valor):
    cursor.execute('SELECT saldo FROM usuarios WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        novo_saldo = row[0] + valor
        cursor.execute('UPDATE usuarios SET saldo = ? WHERE user_id = ?', (novo_saldo, user_id))
    else:
        cursor.execute('INSERT INTO usuarios (user_id, saldo) VALUES (?, ?)', (user_id, valor))
    conn.commit()

# 📌 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Adicionar Saldo", callback_data='adicionar_saldo')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💳 Bem-vindo! Clique no botão abaixo para adicionar saldo:", reply_markup=reply_markup)

# 📌 Botão
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'adicionar_saldo':
        await query.edit_message_text("Digite o valor a adicionar (mínimo R$20,00):")
        context.user_data['esperando_valor'] = True

# 📌 Receber valor e criar pagamento
async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('esperando_valor'):
        return
    try:
        valor = float(update.message.text.replace(',', '.'))
        if valor < 20:
            await update.message.reply_text("⚠️ O valor mínimo é R$20,00.")
            return
    except ValueError:
        await update.message.reply_text("⚠️ Informe um valor válido.")
        return

    user_id = update.message.from_user.id
    custom_id = f"{user_id}_{int(datetime.now().timestamp())}"
    payment_url, payment_token = criar_pagamento_lunarpay(valor, custom_id)
    if not payment_url:
        await update.message.reply_text("❌ Erro ao criar pagamento. Verifique suas credenciais e tente novamente.")
        return

    await update.message.reply_text(
        f"✅ Link gerado com sucesso!\n💳 Valor: R${valor:.2f}\n🔗 {payment_url}\n\n"
        "⏳ Este link expira em 15 minutos."
    )
    context.user_data['esperando_valor'] = False
    context.job_queue.run_once(lambda ctx: monitorar_pagamento(ctx, user_id, payment_token, valor), when=900)

# 📌 Monitorar pagamento e atualizar saldo
def monitorar_pagamento(context: ContextTypes.DEFAULT_TYPE, user_id, payment_token, valor):
    if verificar_pagamento_lunarpay(payment_token):
        atualizar_saldo(user_id, valor)
        context.bot.send_message(chat_id=user_id, text=f"🎉 Pagamento confirmado! Saldo atualizado com R${valor:.2f}.")
    else:
        context.bot.send_message(chat_id=user_id, text="⚠️ O pagamento não foi concluído ou expirou. Tente novamente.")

# 📌 Função principal
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_valor))
    app.run_polling()

if __name__ == '__main__':
    main()
