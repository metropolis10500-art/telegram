const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

// === НАСТРОЙКИ ===
const BOT_TOKEN = '8878972156:AAHIvVDWZvZxGDYE0CqUeOdHTGXoTKOYiSI';
const DB_FILE = './database.json';

const bot = new Telegraf(BOT_TOKEN);

// === ХРАНИЛИЩЕ СОСТОЯНИЙ ===
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
    
    userState[userId] = { targetId: targetId };
    
    await ctx.reply(
      `🤫 <b>Напиши анонимное сообщение для ${targetUser.first_name}</b>\n\n` +
      `Твое имя останется в строжайшем секрете!\n\n✍️ Пиши текст ниже:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  } else {
    delete userState[userId];
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(
      `👋 <b>Добро пожаловать в Шёпот!</b>\n\n` +
      `🤫 100% анонимные сообщения\n` +
      `🕵️‍♂️ Детективный режим (узнай отправителя за Звезды!)\n` +
      `👑 VIP-статус для лучших сыщиков\n\n` +
      `🔗 <b>Твоя личная ссылка:</b>\n<code>${link}</code>\n\n` +
      `⚡️ <i>Скопируй её и закинь в Bio или Stories!</i>`,
      { parse_mode: 'HTML', ...getMainMenu() }
    );
  }
});

// === КНОПКИ МЕНЮ ===

bot.hears('🔗 Моя ссылка', (ctx) => {
  delete userState[ctx.from.id];
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${ctx.from.id}`;
  ctx.reply(`🔗 <b>Твоя ссылка:</b>\n\n<code>${link}</code>`, { parse_mode: 'HTML' });
});

bot.hears('📨 Мои сообщения', (ctx) => {
  delete userState[ctx.from.id];
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 У тебя нет новых сообщений.');

  userState[ctx.from.id] = { msgQueue: msgs.map(m => m.id) };
  showNextMessage(ctx);
});

bot.hears('💎 VIP Статус', (ctx) => {
  delete userState[ctx.from.id];
  ctx.reply(
    `👑 <b>VIP Статус</b>\n\nХочешь всегда знать, кто тебе пишет?\n\n✅ Бесплатное разоблачение\n✅ Значок VIP\n\nСтоимость: <b>299 Stars ⭐️</b> в месяц`,
    {
      parse_mode: 'HTML',
      ...Markup.inlineKeyboard([
        [Markup.button.callback('💳 Купить VIP (⭐️299)', 'buy_vip')]
      ])
    }
  );
});

bot.hears('❓ Помощь', (ctx) => {
  delete userState[ctx.from.id];
  ctx.reply(
    `<b>Как пользоваться:</b>\n\n` +
    `1. Нажми «🔗 Моя ссылка» и скопируй.\n` +
    `2. Опубликуй у себя в профиле/Stories.\n` +
    `3. Люди будут писать тебе анонимно.\n` +
    `4. Хочешь узнать автора? Используй Звезды Telegram ⭐️!`,
    { parse_mode: 'HTML' }
  );
});

// --- ОБРАБОТКА ТЕКСТА ---

bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const state = userState[userId];
  
  if (!state || !state.targetId) {
      return ctx.reply('Выбери действие в меню 👇', getMainMenu());
  }
  
  const targetId = state.targetId;
  const text = ctx.message.text;
  
  if (text.length > 200) return ctx.reply('Слишком длинное! Максимум 200 символов.');

  const senderName = ctx.from.first_name || 'Аноним';
  const hint = `Имя начинается на: <b>${senderName.charAt(0).toUpperCase()}...</b>`;

  addMessage(targetId, text, hint);
  delete userState[userId];

  await ctx.reply('✅ Доставлено! Никто не узнает, кто отправил 🤫', getMainMenu());

  try {
    await bot.telegram.sendMessage(targetId, '🤫 <b>Тебе пришло новое анонимное сообщение!</b>', {
      parse_mode: 'HTML',
      reply_markup: Markup.inlineKeyboard([[Markup.button.callback('📨 Прочитать', 'read_messages')]])
    });
  } catch (e) {}
});

// === ИНЛАЙН КНОПКИ (Чтение и Покупка) ===

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
      `🤫 <b>Анонимное сообщение:</b>\n\n"${msg.text}"\n\nХочешь узнать, кто это?`,
      { parse_mode: 'HTML', ...Markup.inlineKeyboard([
        [Markup.button.callback('🔍 Подсказка (⭐️50)', `buy_hint_${msg.id}`)],
        [Markup.button.callback('🕵️ Кто это? (⭐️150)', `buy_reveal_${msg.id}`)],
        [Markup.button.callback('➡️ Следующее', 'skip_msg')]
      ])}
    );
  }
}

bot.action('skip_msg', (ctx) => {
  ctx.answerCbQuery();
  showNextMessage(ctx);
});

// === ПЛАТЕЖНАЯ СИСТЕМА TELEGRAM STARS ===

// Обработчик покупки VIP
bot.action('buy_vip', async (ctx) => {
    await ctx.answerCbQuery();
    await ctx.replyWithInvoice({
        title: '👑 VIP Статус (1 месяц)',
        description: 'Бесплатное разоблачение всех анонимов на 30 дней!',
        payload: 'vip_purchase',
        currency: 'XTR', // Специальная валюта Telegram Stars
        prices: [{ label: 'VIP', amount: 299 }], // Цена в Звездах
        provider_token: '' // Должно быть пусто для Stars!
    });
});

// Обработчик покупки Подсказки
bot.action(/^buy_hint_(.+)$/, async (ctx) => {
    const msgId = ctx.match[1];
    await ctx.answerCbQuery();
    await ctx.replyWithInvoice({
        title: '🔍 Подсказка отправителя',
        description: 'Узнать первую букву имени анонима',
        payload: `hint_${msgId}`,
        currency: 'XTR',
        prices: [{ label: 'Подсказка', amount: 50 }],
        provider_token: ''
    });
});

// Обработчик покупки Разоблачения
bot.action(/^buy_reveal_(.+)$/, async (ctx) => {
    const msgId = ctx.match[1];
    await ctx.answerCbQuery();
    await ctx.replyWithInvoice({
        title: '🕵️ Полное разоблачение',
        description: 'Узнать, кто отправил это сообщение',
        payload: `reveal_${msgId}`,
        currency: 'XTR',
        prices: [{ label: 'Разоблачение', amount: 150 }],
        provider_token: ''
    });
});

// Подтверждение предзаказа (Telegram ждет этого от бота)
bot.on('pre_checkout_query', (ctx) => {
    ctx.answerPreCheckoutQuery(true); // Подтверждаем оплату
});

// Успешная оплата
bot.on('successful_payment', async (ctx) => {
    const payload = ctx.message.successful_payment.invoice_payload;
    const userId = ctx.from.id;
    
    const db = loadDB();

    if (payload === 'vip_purchase') {
        const expiry = Date.now() + 30 * 24 * 60 * 60 * 1000;
        if (!db.users[userId]) registerUser(userId, 'user', 'User');
        db.users[userId].is_vip = true;
        db.users[userId].vip_expiry = expiry;
        saveDB(db);
        ctx.reply('👑 <b>VIP Статус активирован на 30 дней!</b>\nТеперь ты видишь всех отправителей бесплатно!', { parse_mode: 'HTML' });
    } else {
        const parts = payload.split('_');
        const type = parts[0];
        const msgId = parseInt(parts[1]);
        const msg = db.messages.find(m => m.id === msgId);

        if (msg) {
            if (type === 'hint') {
                msg.hint_bought = true;
                saveDB(db);
                ctx.reply(`🔍 <b>Подсказка:</b>\n${msg.sender_hint}`, { parse_mode: 'HTML' });
            } else if (type === 'reveal') {
                msg.reveal_bought = true;
                saveDB(db);
                ctx.reply(`🕵️ <b>Разоблачение!</b>\nОтправитель начинается на букву, указанную в подсказке!`, { parse_mode: 'HTML' });
            }
        } else {
            ctx.reply('Ошибка: сообщение не найдено.');
        }
    }
});

// === ЗАПУСК ===
bot.launch().then(() => {
    console.log('🤖 Бот "Шёпот" со Stars запущен!');
}).catch((err) => console.error('Ошибка бота:', err));

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
