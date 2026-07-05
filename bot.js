const { Telegraf, Markup } = require('telegraf');
const express = require('express');
const fs = require('fs');

// === НАСТРОЙКИ ===
const BOT_TOKEN = '8038462440:AAEoCfxTBFwfJhhDjRRJcOKhB9820rqGs6o';
const YOOMONEY_WALLET = '4100118935779591';
const PORT = process.env.PORT || 3000;
const DB_FILE = './database.json';

const bot = new Telegraf(BOT_TOKEN);
const app = express();

// === ХРАНИЛИЩЕ СОСТОЯНИЙ (Вместо сессий, чтобы не качать лишние пакеты) ===
const userState = {}; 

// === БАЗА ДАННЫХ (JSON) ===
if (!fs.existsSync(DB_FILE)) {
    fs.writeFileSync(DB_FILE, JSON.stringify({ users: {}, messages: [] }));
}

function loadDB() {
    const data = fs.readFileSync(DB_FILE, 'utf8');
    return JSON.parse(data);
}

function saveDB(db) {
    fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
}

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    const db = loadDB();
    if (!db.users[tg_id]) {
        db.users[tg_id] = { username, first_name, is_vip: false, vip_expiry: 0 };
        saveDB(db);
    }
}

function addMessage(target_id, text, sender_hint) {
    const db = loadDB();
    const id = Date.now(); 
    db.messages.push({ id, target_id, text, sender_hint, is_read: false, hint_bought: false, reveal_bought: false });
    saveDB(db);
}

function getUnreadMessages(target_id) {
    const db = loadDB();
    return db.messages.filter(m => m.target_id === target_id && !m.is_read);
}

function getMessageById(id) {
    const db = loadDB();
    return db.messages.find(m => m.id === id);
}

function markAsRead(id) {
    const db = loadDB();
    const msg = db.messages.find(m => m.id === id);
    if (msg) { msg.is_read = true; saveDB(db); }
}

// === КРАСИВЫЙ ДИЗАЙН (UI) ===
function getMainMenu() {
  return Markup.keyboard([
    ['📨 Мои сообщения', '🔗 Моя ссылка'],
    ['💎 VIP Статус', '❓ Помощь']
  ]).resize();
}

// === ЛОГИКА БОТА ===

bot.start(async (ctx) => {
  const userId = ctx.from.id;
  registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Аноним');
  
  const payload = ctx.startPayload;

  if (payload && payload.startsWith('w_')) {
    const targetId = parseInt(payload.replace('w_', ''));
    const db = loadDB();
    const targetUser = db.users[targetId];
    if (!targetUser) return ctx.reply('Этот пользователь еще не в игре :(');
    
    // Сохраняем состояние юзера: он сейчас пишет кому-то
    userState[userId] = { targetId: targetId };
    
    await ctx.reply(
      `🤫 <b>Напиши анонимное сообщение для ${targetUser.first_name}</b>\n\n` +
      `Твое имя останется в строжайшем секрете. Пиши всё, что думаешь!\n\n` +
      `✍️ Пиши текст ниже:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  } else {
    // Очищаем состояние, если юзер просто перезапустил бота
    delete userState[userId];
    
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(
      `👋 <b>Добро пожаловать в Шёпот!</b>\n\n` +
      `Это место, где рождаются секреты и интриги.\n\n` +
      `👇 <b>Что тут есть:</b>\n` +
      `🤫 100% анонимные сообщения\n` +
      `🕵️‍♂️ Детективный режим (узнай отправителя!)\n` +
      `👑 VIP-статус для лучших сыщиков\n\n` +
      `🔗 <b>Твоя личная ссылка:</b>\n<code>${link}</code>\n\n` +
      `⚡️ <i>Скопируй её и закинь в Bio или Stories!</i>`,
      { parse_mode: 'HTML', ...getMainMenu() }
    );
  }
});

// ==========================================================
// --- КНОПКИ МЕНЮ (ОБЯЗАТЕЛЬНО ДО bot.on('text')) !!! ---
// ==========================================================

bot.hears('🔗 Моя ссылка', (ctx) => {
  delete userState[ctx.from.id]; // Сбрасываем режим написания
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${ctx.from.id}`;
  ctx.reply(`🔗 <b>Твоя ссылка для анонимных сообщений:</b>\n\n<code>${link}</code>\n\nПоделись ей!`, { parse_mode: 'HTML' });
});

bot.hears('📨 Мои сообщения', (ctx) => {
  delete userState[ctx.from.id]; // Сбрасываем режим написания
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 У тебя нет новых сообщений. Поделись ссылкой!');

  userState[ctx.from.id] = { msgQueue: msgs.map(m => m.id) };
  showNextMessage(ctx);
});

bot.hears('💎 VIP Статус', (ctx) => {
  delete userState[ctx.from.id]; // Сбрасываем режим написания
  ctx.reply(
    `👑 <b>VIP Статус</b>\n\nХочешь всегда знать, кто тебе пишет?\n\nПреимущества VIP:\n✅ Бесплатное полное разоблачение отправителей\n✅ Значок VIP в профиле\n✅ Приоритетная поддержка\n\nСтоимость: <b>299 ₽ / месяц</b>`,
    {
      parse_mode: 'HTML',
      ...Markup.inlineKeyboard([
        [Markup.button.url('💳 Купить VIP (299 ₽)', generatePaymentLink(ctx.from.id, 'vip', 299.00))]
      ])
    }
  );
});

bot.hears('❓ Помощь', (ctx) => {
  delete userState[ctx.from.id]; // Сбрасываем режим написания
  ctx.reply(
    `<b>Как пользоваться ботом:</b>\n\n` +
    `1. Нажми «🔗 Моя ссылка» и скопируй её.\n` +
    `2. Отправь эту ссылку друзьям или опубликуй у себя в профиле/Stories.\n` +
    `3. Люди будут переходить и писать тебе анонимные сообщения.\n` +
    `4. Нажми «📨 Мои сообщения», чтобы прочитать их.\n` +
    `5. Если хочешь узнать, кто автор — покупай подсказки или полное разоблачение! 🕵️‍♂️`,
    { parse_mode: 'HTML' }
  );
});

// --- ОБРАБОТКА ТЕКСТА (Отправка анонимного сообщения) ---

bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const state = userState[userId];
  
  // Если юзер не в режиме отправки сообщения, просим использовать меню
  if (!state || !state.targetId) {
      return ctx.reply('Выбери действие в меню ниже 👇', getMainMenu());
  }
  
  const targetId = state.targetId;
  const text = ctx.message.text;
  
  if (text.length > 200) return ctx.reply('Слишком длинное сообщение! Максимум 200 символов.');

  const senderName = ctx.from.first_name || 'Аноним';
  const hint = `Имя начинается на: <b>${senderName.charAt(0).toUpperCase()}...</b>`;

  addMessage(targetId, text, hint);
  delete userState[userId]; // Сбрасываем состояние после отправки

  await ctx.reply('✅ Сообщение доставлено! Никто не узнает, кто его отправил 🤫', getMainMenu());

  try {
    await bot.telegram.sendMessage(targetId, '🤫 <b>Тебе пришло новое анонимное сообщение!</b>\nНажми кнопку ниже, чтобы прочитать.', {
      parse_mode: 'HTML',
      reply_markup: Markup.inlineKeyboard([[Markup.button.callback('📨 Прочитать', 'read_messages')]])
    });
  } catch (e) {}
});

// === ИНЛАЙН КНОПКИ (Под сообщениями) ===

bot.action('read_messages', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.answerCbQuery('Сообщений нет!');
  
  userState[ctx.from.id] = { msgQueue: msgs.map(m => m.id) };
  showNextMessage(ctx);
});

function showNextMessage(ctx) {
  const userId = ctx.from.id;
  const state = userState[userId];

  if (!state || !state.msgQueue || state.msgQueue.length === 0) {
    return ctx.reply('📭 Все сообщения прочитаны!', getMainMenu());
  }

  const msgId = state.msgQueue.shift();
  const msg = getMessageById(msgId);
  
  if (!msg) return showNextMessage(ctx);

  markAsRead(msg.id);

  const db = loadDB();
  const user = db.users[userId];
  const isVip = user && user.is_vip && user.vip_expiry > Date.now();

  if (isVip || msg.reveal_bought) {
    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n\n"${msg.text}"\n\n🕵️ <b>Разоблачение:</b> ${msg.sender_hint.replace('...', ctx.from.first_name)}`,
      { parse_mode: 'HTML' }
    );
    return showNextMessage(ctx);
  } else {
    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n\n"${msg.text}"\n\nХочешь узнать, кто это написал?`,
      { parse_mode: 'HTML', ...Markup.inlineKeyboard([
        [Markup.button.url('🔍 Подсказка (50 ₽)', generatePaymentLink(ctx.from.id, `hint_${msg.id}`, 50.00))],
        [Markup.button.url('🕵️ Кто это? (150 ₽)', generatePaymentLink(ctx.from.id, `reveal_${msg.id}`, 150.00))],
        [Markup.button.callback('➡️ Следующее', 'skip_msg')]
      ])}
    );
  }
}

bot.action('skip_msg', (ctx) => {
  ctx.answerCbQuery();
  showNextMessage(ctx);
});

// === ПЛАТЕЖНАЯ СИСТЕМА ЮMONEY ===

function generatePaymentLink(userId, label, amount) {
  return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=shop&targets=WhisperBot&paymentType=AC&amount=${amount}&label=${userId}_${label}`;
}

// Веб-сервер (Заглушка)
app.get('/', (req, res) => res.send('Bot is running!'));

// === ЗАПУСК ===
app.listen(PORT, () => {
  console.log(`🚀 Веб-сервер запущен на порту ${PORT}`);
  bot.launch().then(() => {
    console.log('🤖 Бот "Шёпот" запущен!');
  }).catch((err) => console.error('Ошибка бота:', err));
});

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
