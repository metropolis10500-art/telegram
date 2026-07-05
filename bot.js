const { Telegraf, Markup } = require('telegraf');
const express = require('express');
const crypto = require('crypto');
const initSqlJs = require('sql.js');
const fs = require('fs');

// === НАСТРОЙКИ ===
const BOT_TOKEN = '8038462440:AAEoCfxTBFwfJhhDjRRJcOKhB9820rqGs6o';
const YOOMONEY_WALLET = '4100118935779591';
const YOOMONEY_SECRET = '5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191';
const PORT = process.env.PORT || 3000;
const DB_PATH = './whisper_database.sqlite';

const bot = new Telegraf(BOT_TOKEN);
const app = express();

// === БАЗА ДАННЫХ (sql.js - Чистый JS, без компиляции) ===
let db;

async function initDatabase() {
  const SQL = await initSqlJs();
  
  // Если файл базы существует, загружаем его с диска
  if (fs.existsSync(DB_PATH)) {
    const fileBuffer = fs.readFileSync(DB_PATH);
    db = new SQL.Database(fileBuffer);
    console.log('✅ База данных загружена с диска');
  } else {
    db = new SQL.Database();
    console.log('✅ Создана новая база данных');
  }

  // Создаем таблицы
  db.run(`
    CREATE TABLE IF NOT EXISTS users (
      tg_id INTEGER PRIMARY KEY,
      username TEXT,
      first_name TEXT,
      is_vip INTEGER DEFAULT 0,
      vip_expiry INTEGER DEFAULT 0
    )
  `);
  db.run(`
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      target_id INTEGER,
      sender_hint TEXT,
      text TEXT,
      is_read INTEGER DEFAULT 0,
      hint_bought INTEGER DEFAULT 0,
      reveal_bought INTEGER DEFAULT 0
    )
  `);
  db.run(`CREATE INDEX IF NOT EXISTS idx_target ON messages(target_id, is_read)`);
  
  saveDatabase(); // Сохраняем структуру на диск
}

// Функция сохранения базы на диск (вызывается после каждого изменения)
function saveDatabase() {
  const data = db.export();
  const buffer = Buffer.from(data);
  fs.writeFileSync(DB_PATH, buffer);
}

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
  const res = db.prepare('SELECT tg_id FROM users WHERE tg_id = ?').get([tg_id]);
  if (!res) {
    db.prepare('INSERT INTO users (tg_id, username, first_name) VALUES (?, ?, ?)').run([tg_id, username, first_name]);
    saveDatabase();
  }
}

function addMessage(target_id, text, sender_hint) {
  db.prepare('INSERT INTO messages (target_id, text, sender_hint) VALUES (?, ?, ?)').run([target_id, text, sender_hint]);
  saveDatabase();
}

function getUnreadMessages(target_id) {
  return db.prepare('SELECT * FROM messages WHERE target_id = ? AND is_read = 0').all([target_id]);
}

function getMessageById(id) {
  return db.prepare('SELECT * FROM messages WHERE id = ?').get([id]);
}

function markAsRead(id) {
  db.prepare('UPDATE messages SET is_read = 1 WHERE id = ?').run([id]);
  saveDatabase();
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
    const targetUser = db.prepare('SELECT * FROM users WHERE tg_id = ?').get([targetId]);
    if (!targetUser) return ctx.reply('Этот пользователь не пользуется ботом :(');
    
    ctx.session = ctx.session || {};
    ctx.session.targetId = targetId;
    
    await ctx.reply(
      `🤫 <b>Напиши анонимное сообщение для ${targetUser.first_name}</b>\n\nТвое имя останется в секрете. Пиши всё, что думаешь!`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  } else {
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(
      `👋 <b>Добро пожаловать в Шёпот!</b>\n\nЗдесь ты можешь получать анонимные сообщения от друзей и незнакомцев.\n\nТвоя личная ссылка:\n<code>${link}</code>\n\nСкинь её в Stories или Bio, чтобы начать получать послания! 👇`,
      { parse_mode: 'HTML', ...getMainMenu() }
    );
  }
});

bot.on('text', async (ctx) => {
  if (!ctx.session || !ctx.session.targetId) return;
  
  const targetId = ctx.session.targetId;
  const text = ctx.message.text;
  
  if (text.length > 200) return ctx.reply('Слишком длинное сообщение! Максимум 200 символов.');

  const senderName = ctx.from.first_name || 'Аноним';
  const hint = `Имя начинается на: <b>${senderName.charAt(0).toUpperCase()}...</b>`;

  addMessage(targetId, text, hint);
  ctx.session.targetId = null; 

  await ctx.reply('✅ Сообщение доставлено! Никто не узнает, кто его отправил 🤫', getMainMenu());

  try {
    await bot.telegram.sendMessage(targetId, '🤫 <b>Тебе пришло новое анонимное сообщение!</b>\nНажми кнопку ниже, чтобы прочитать.', {
      parse_mode: 'HTML',
      reply_markup: Markup.inlineKeyboard([
        [Markup.button.callback('📨 Прочитать', 'read_messages')]
      ])
    });
  } catch (e) { console.log('Не смогли отправить уведомление'); }
});

// === КНОПКИ МЕНЮ ===

bot.hears('🔗 Моя ссылка', (ctx) => {
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${ctx.from.id}`;
  ctx.reply(`🔗 <b>Твоя ссылка для анонимных сообщений:</b>\n\n<code>${link}</code>\n\nПоделись ей!`, { parse_mode: 'HTML' });
});

bot.hears('📨 Мои сообщения', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 У тебя нет новых сообщений. Поделись ссылкой!');

  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);

  showNextMessage(ctx);
});

bot.hears('💎 VIP Статус', (ctx) => {
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

// === ИНЛАЙН КНОПКИ (Чтение и Покупки) ===

bot.action('read_messages', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.answerCbQuery('Сообщений нет!');
  
  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);
  showNextMessage(ctx);
});

function showNextMessage(ctx) {
  if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) {
    return ctx.reply('📭 Все сообщения прочитаны!', getMainMenu());
  }

  const msgId = ctx.session.msgQueue.shift();
  const msg = getMessageById(msgId);
  
  if (!msg) return showNextMessage(ctx);

  markAsRead(msg.id);

  const user = db.prepare('SELECT * FROM users WHERE tg_id = ?').get([ctx.from.id]);
  const isVip = user && (user.is_vip === 1 && user.vip_expiry > Date.now());

  let buttons = [];
  
  if (isVip || msg.reveal_bought) {
    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n\n"${msg.text}"\n\n🕵️ <b>Разоблачение:</b> ${msg.sender_hint.replace('...', ctx.from.first_name)}`,
      { parse_mode: 'HTML' }
    );
    return showNextMessage(ctx);
  } else {
    buttons.push([
      Markup.button.url('🔍 Подсказка (50 ₽)', generatePaymentLink(ctx.from.id, `hint_${msg.id}`, 50.00)),
      Markup.button.url('🕵️ Кто это? (150 ₽)', generatePaymentLink(ctx.from.id, `reveal_${msg.id}`, 150.00))
    ]);
    buttons.push([Markup.button.callback('➡️ Следующее', 'skip_msg')]);

    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n\n"${msg.text}"\n\nХочешь узнать, кто это написал?`,
      { parse_mode: 'HTML', ...Markup.inlineKeyboard(buttons) }
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

app.use(express.urlencoded({ extended: true }));

app.post('/yoomoney-webhook', (req, res) => {
  const { notification_type, operation_id, amount, currency, datetime, sender, codepro, label, sha1_hash } = req.body;

  const hashString = `${notification_type}&${operation_id}&${amount}&${currency}&${datetime}&${sender}&${codepro}&${YOOMONEY_SECRET}&${label}`;
  const myHash = crypto.createHash('sha1').update(hashString).digest('hex');

  if (myHash === sha1_hash && codepro === 'false') {
    console.log(`✅ Оплата подтверждена! Label: ${label}`);

    const parts = label.split('_');
    const userId = parseInt(parts[0]);
    const paymentType = parts[1];

    if (paymentType === 'vip') {
      const expiry = Date.now() + 30 * 24 * 60 * 60 * 1000;
      db.prepare('UPDATE users SET is_vip = 1, vip_expiry = ? WHERE tg_id = ?').run([expiry, userId]);
      saveDatabase();
      bot.telegram.sendMessage(userId, '👑 <b>VIP Статус активирован!</b>\nТеперь ты будешь видеть всех отправителей!', { parse_mode: 'HTML' });
    } else if (paymentType === 'hint' || paymentType === 'reveal') {
      const msgId = parseInt(parts[2]);
      const msg = getMessageById(msgId);
      
      if (msg) {
        if (paymentType === 'hint') {
          db.prepare('UPDATE messages SET hint_bought = 1 WHERE id = ?').run([msgId]);
          saveDatabase();
          bot.telegram.sendMessage(userId, `🔍 <b>Подсказка:</b>\n${msg.sender_hint}`, { parse_mode: 'HTML' });
        } else if (paymentType === 'reveal') {
          db.prepare('UPDATE messages SET reveal_bought = 1 WHERE id = ?').run([msgId]);
          saveDatabase();
          bot.telegram.sendMessage(userId, `🕵️ <b>Разоблачение!</b>\nОтправитель начинается на букву, указанную в подсказке!`, { parse_mode: 'HTML' });
        }
      }
    }
    res.send('OK');
  } else {
    res.status(400).send('Invalid hash');
  }
});

// === ЗАПУСК ===
async function startBot() {
  await initDatabase(); // Инициализируем локальную базу

  app.listen(PORT, () => {
    console.log(`🚀 Веб-сервер запущен на порту ${PORT}`);
    bot.launch().then(() => {
      console.log('🤖 Бот "Шёпот" запущен!');
    }).catch((err) => console.error('Ошибка бота:', err));
  });
}

startBot();

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
