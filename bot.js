const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

// === НАСТРОЙКИ ===
const BOT_TOKEN = '8878972156:AAHIvVDWZvZxGDYE0CqUeOdHTGXoTKOYiSI';
const YOOMONEY_WALLET = '4100118935779591';
const YOOMONEY_API_TOKEN = '5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191'; // Тот же токен, что и для Python
const DB_FILE = './database.json';

const bot = new Telegraf(BOT_TOKEN);
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

// === КЛАВИАТУРЫ ===
function getMainMenu() {
  return Markup.keyboard([
    ['📨 Мои сообщения', '🔗 Моя ссылка'],
    ['💎 VIP Статус', '❓ Помощь']
  ]).resize();
}

// === ПЛАТЕЖНАЯ СИСТЕМА ЮMONEY ===

// 1. Генерация ссылки (ИСПОЛЬЗУЕМ SMALL !!!)
function generatePaymentLink(amount, label) {
  return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=small&targets=WhisperBot&paymentType=AC&amount=${amount}&label=${label}`;
}

// 2. Проверка оплаты через API (То же самое, что делает библиотека на Python)
async function checkYooMoneyPayment(label) {
  try {
    const params = new URLSearchParams();
    params.append('label', label);
    params.append('type', 'in');

    const response = await fetch('https://yoomoney.ru/api/operation-history', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: params.toString()
    });

    const data = await response.json();
    
    if (data.operations && data.operations.length > 0) {
      const successfulOp = data.operations.find(op => op.status === 'success');
      if (successfulOp) return true;
    }
    return false;
  } catch (error) {
    console.error('Ошибка проверки API ЮMoney:', error);
    return false;
  }
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
      `🤫 <b>Напиши анонимное сообщение для ${targetUser.first_name}</b>\n\nТвое имя останется в секрете!\n\n✍️ Пиши текст ниже:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  } else {
    delete userState[userId];
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(
      `👋 <b>Добро пожаловать в Шёпот!</b>\n\n🤫 Анонимные сообщения\n🕵️‍♂️ Узнай отправителя!\n👑 VIP-статус\n\n🔗 <b>Твоя ссылка:</b>\n<code>${link}</code>`,
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
  const label = `${ctx.from.id}_vip`;
  const link = generatePaymentLink(299.00, label);
  ctx.reply(
    `👑 <b>VIP Статус</b>\n\n✅ Бесплатное разоблачение навсегда\n\nСтоимость: <b>299 ₽</b>`,
    {
      parse_mode: 'HTML',
      ...Markup.inlineKeyboard([
        [Markup.button.url('💳 Перейти к оплате (299 ₽)', link)],
        [Markup.button.callback('✅ Я оплатил', `check_vip`)]
      ])
    }
  );
});

bot.hears('❓ Помощь', (ctx) => {
  delete userState[ctx.from.id]; 
  ctx.reply(
    `<b>Как пользоваться:</b>\n\n1. Нажми «🔗 Моя ссылка» и скопируй.\n2. Опубликуй у себя в профиле/Stories.\n3. Люди будут писать тебе анонимно.\n4. Узнай автора за рубли! 🕵️‍♂️`,
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

// === ИНЛАЙН КНОПКИ ===

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
    const hintLabel = `${userId}_hint_${msg.id}`;
    const revealLabel = `${userId}_reveal_${msg.id}`;
    
    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n\n"${msg.text}"\n\nХочешь узнать, кто это?`,
      { parse_mode: 'HTML', ...Markup.inlineKeyboard([
        [Markup.button.url('🔍 Подсказка (50 ₽)', generatePaymentLink(50.00, hintLabel))],
        [Markup.button.callback('✅ Оплатил подсказку', `check_hint_${msg.id}`)],
        [Markup.button.url('🕵️ Кто это? (150 ₽)', generatePaymentLink(150.00, revealLabel))],
        [Markup.button.callback('✅ Оплатил разоблачение', `check_reveal_${msg.id}`)],
        [Markup.button.callback('➡️ Следующее', 'skip_msg')]
      ])}
    );
  }
}

bot.action('skip_msg', (ctx) => {
  ctx.answerCbQuery();
  showNextMessage(ctx);
});

// === ОБРАБОТКА ОПЛАТЫ ===

bot.action('check_vip', async (ctx) => {
  await ctx.answerCbQuery('Проверяю оплату... ⏳');
  const label = `${ctx.from.id}_vip`;
  const isPaid = await checkYooMoneyPayment(label);

  if (isPaid) {
    const db = loadDB();
    const userId = ctx.from.id;
    if (!db.users[userId]) registerUser(userId, 'user', 'User');
    db.users[userId].is_vip = true;
    db.users[userId].vip_expiry = Date.now() + 30 * 24 * 60 * 60 * 1000;
    saveDB(db);
    ctx.reply('👑 <b>VIP Статус активирован!</b>\nТеперь ты видишь всех отправителей!', { parse_mode: 'HTML' });
  } else {
    ctx.reply('❌ Оплата не найдена. Убедитесь, что вы перевели деньги, и попробуйте снова через минуту.');
  }
});

bot.action(/^check_hint_(.+)$/, async (ctx) => {
  const msgId = ctx.match[1];
  await ctx.answerCbQuery('Проверяю оплату... ⏳');
  const label = `${ctx.from.id}_hint_${msgId}`;
  const isPaid = await checkYooMoneyPayment(label);

  if (isPaid) {
    const db = loadDB();
    const msg = db.messages.find(m => m.id === parseInt(msgId));
    if (msg) {
      msg.hint_bought = true;
      saveDB(db);
      ctx.reply(`🔍 <b>Подсказка:</b>\n${msg.sender_hint}`, { parse_mode: 'HTML' });
    }
  } else {
    ctx.reply('❌ Оплата не найдена.');
  }
});

bot.action(/^check_reveal_(.+)$/, async (ctx) => {
  const msgId = ctx.match[1];
  await ctx.answerCbQuery('Проверяю оплату... ⏳');
  const label = `${ctx.from.id}_reveal_${msgId}`;
  const isPaid = await checkYooMoneyPayment(label);

  if (isPaid) {
    const db = loadDB();
    const msg = db.messages.find(m => m.id === parseInt(msgId));
    if (msg) {
      msg.reveal_bought = true;
      saveDB(db);
      ctx.reply(`🕵️ <b>Разоблачение!</b>\nОтправитель начинается на букву из подсказки!`, { parse_mode: 'HTML' });
    }
  } else {
    ctx.reply('❌ Оплата не найдена.');
  }
});

// === ЗАПУСК ===
bot.launch().then(() => {
    console.log('🤖 Бот "Шёпот" с YooMoney API запущен!');
}).catch((err) => console.error('Ошибка бота:', err));

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
