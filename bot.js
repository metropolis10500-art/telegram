const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

// === НАСТРОЙКИ ===
const BOT_TOKEN = '8878972156:AAHIvVDWZvZxGDYE0CqUeOdHTGXoTKOYiSI';
const YOOMONEY_WALLET = '4100118935779591';
const YOOMONEY_API_TOKEN = '5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191';
const DB_FILE = './database.json';
const ADMIN_ID = 5494544187; // ВСТАВЬ СЮДА СВОЙ TELEGRAM ID (числом)

const bot = new Telegraf(BOT_TOKEN);

// === ОПТИМИЗИРОВАННАЯ БАЗА ДАННЫХ ===
let db = { users: {}, messages: {} };
if (fs.existsSync(DB_FILE)) {
    try {
        const loadedData = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        db.users = loadedData.users || {};
        if (Array.isArray(loadedData.messages)) { 
            loadedData.messages.forEach(m => db.messages[m.id] = m); 
        } else { 
            db.messages = loadedData.messages || {}; 
        }
    } catch (e) { console.error('Ошибка загрузки БД:', e); }
}

let saveTimeout = null;
function scheduleSave() {
    if (!saveTimeout) {
        saveTimeout = setTimeout(() => { 
            fs.writeFile(DB_FILE, JSON.stringify(db, null, 2), (err) => { if (err) console.error(err); }); 
            saveTimeout = null; 
        }, 2000);
    }
}

// Автоочистка старых сообщений (раз в час)
setInterval(() => {
    const threeDaysAgo = Date.now() - 3 * 24 * 60 * 60 * 1000;
    let deletedCount = 0;
    Object.keys(db.messages).forEach(id => { 
        if (db.messages[id].is_read && db.messages[id].id < threeDaysAgo) { 
            delete db.messages[id]; deletedCount++; 
        } 
    });
    if (deletedCount > 0) { console.log(`🧹 Удалено ${deletedCount} старых сообщений`); scheduleSave(); }
}, 3600000);

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    if (!db.users[tg_id]) { 
        db.users[tg_id] = { username, first_name, is_vip: false, vip_expiry: 0, is_premium: false, premium_expiry: 0, reveal_credits: 0 }; 
        scheduleSave(); 
    }
}

function addMessage(target_id, text, sender_name, sender_photo, aura = "🌙 Нейтральная") { 
    const id = Date.now(); 
    db.messages[id] = { id, target_id, text, sender_name, sender_photo, aura, is_read: false, reveal_bought: false }; 
    scheduleSave(); 
    return id; 
}

function getUnreadMessages(target_id) { 
    return Object.values(db.messages).filter(m => m.target_id === target_id && !m.is_read).sort((a, b) => b.id - a.id); 
}

function getMessageById(id) { return db.messages[id]; }

function markAsRead(id) { const m = db.messages[id]; if (m) { m.is_read = true; scheduleSave(); } }

// === УТИЛИТЫ ===
function detectAura(text) { 
    const t = text.toLowerCase(); 
    if (t.match(/люблю|нрав|красив|горяч/)) return "🔥 Пылкая"; 
    if (t.match(/ненави|дурак|туп/)) return "⚡️ Грозовая"; 
    if (t.match(/скуч|грус/)) return "🌧 Туманная"; 
    return "🌙 Лунная"; 
}

function getMainMenu() { 
    return Markup.keyboard([
        ['📨 Мои сообщения', '🔗 Моя ссылка'], 
        ['💰 Магазин', '❓ Помощь']
    ]).resize(); 
}

function generatePaymentLink(amount, label) { 
    return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=small&paymentType=AC&sum=${amount}&label=${label}`; 
}

async function checkYooMoneyPayment(label) { 
    try { 
        const p = new URLSearchParams(); 
        p.append('label', label); 
        p.append('type', 'in'); 
        const r = await fetch('https://yoomoney.ru/api/operation-history', { 
            method: 'POST', 
            headers: { 'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`, 'Content-Type': 'application/x-www-form-urlencoded' }, 
            body: p.toString() 
        }); 
        const d = await r.json(); 
        return d.operations && d.operations.some(o => o.status === 'success'); 
    } catch (e) { return false; } 
}

let adminState = {};

// =====================================================================
// === ЛОГИКА БОТА ===
// =====================================================================

bot.start(async (ctx) => {
  const userId = ctx.from.id;
  registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Аноним');
  const payload = ctx.startPayload;

  if (payload && payload.startsWith('w_')) {
    // ВХОД ПО ССЫЛКЕ (Отправитель)
    const targetId = parseInt(payload.replace('w_', ''));
    const targetUser = db.users[targetId];
    if (!targetUser) return ctx.reply('Этот пользователь еще не пользуется Шёпотом :(');
    
    ctx.session = { targetId: targetId, sender_step: 'ask_name' };
    await ctx.reply(
      `🤫 <b>Ты хочешь отправить тайну для ${targetUser.first_name}</b>\n\n` +
      `Правила Шёпота: мы просим тебя загрузить <b>своё реальное фото и имя</b>.\n` +
      `Не переживай, получатель увидит их <b>ТОЛЬКО после оплаты</b>. А пока — ты в тени!\n\n` +
      `👤 Напиши своё реальное имя:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  } else {
    // ОБЫЧНЫЙ ВХОД (Получатель)
    ctx.session = {};
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    const user = db.users[userId];
    const badge = user.is_premium ? '👑' : (user.is_vip ? '💎' : '');
    await ctx.reply(
      `👋 <b>Добро пожаловать в Шёпот, ${badge} ${ctx.from.first_name}!</b>\n\n` +
      `Это место, где тайны обретают лица.\n\n` +
      `📲 Скидывай свою ссылку в соцсети (Instagram, TikTok, VK).\n` +
      `🤫 Тебе будут писать анонимные послания.\n` +
      `📸 Но есть подвох: чтобы узнать, <b>кто именно</b> тебе написал и увидеть его фото — придётся заплатить!\n\n` +
      `🔗 <b>Твоя ссылка:</b>\n<code>${link}</code>`,
      { parse_mode: 'HTML', ...getMainMenu() }
    );
  }
});

// --- КНОПКИ МЕНЮ ---
bot.hears('🔗 Моя ссылка', (ctx) => {
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${ctx.from.id}`;
  ctx.reply(`🔗 <b>Скидывай эту ссылку в соцсети:</b>\n\n<code>${link}</code>\n\nЛюди будут переходить, писать тебе секреты и загружать свои фото! 📸`, { parse_mode: 'HTML' });
});

bot.hears('📨 Мои сообщения', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 Пока пусто... Поделись ссылкой в соцсетях!');
  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);
  showNextMessage(ctx);
});

bot.hears('💰 Магазин', (ctx) => {
  ctx.reply(
    `💰 <b>Магазин</b>\n\nХочешь увидеть, кто скрывается за анонимом? Выбери тариф:`,
    { parse_mode: 'HTML', ...Markup.inlineKeyboard([
      [Markup.button.callback('📸 Открыть 1 фото и имя (149 ₽)', 'shop_reveal')],
      [Markup.button.callback('💎 VIP — 5 открытий (399 ₽)', 'shop_vip')],
      [Markup.button.callback('👑 PREMIUM — Безлимит (799 ₽)', 'shop_premium')]
    ])}
  );
});

bot.hears('❓ Помощь', (ctx) => {
  ctx.reply(
    `<b>❓ Как работает Шёпот?</b>\n\n` +
    `1. Скопируй ссылку и кидай её куда угодно (Instagram, TikTok).\n` +
    `2. Люди переходят, пишут тебе послания и <b>загружают своё реальное фото</b>.\n` +
    `3. Ты читаешь текст бесплатно.\n` +
    `4. Хочешь увидеть лицо автора? Покупай открытие в Магазине! 📸`,
    { parse_mode: 'HTML' }
  );
});

// --- ОБРАБОТКА ФОТОГРАФИЙ (Шаг 2 для отправителя) ---
bot.on('photo', async (ctx) => {
  if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
  
  const photoId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
  ctx.session.sender_photo = photoId;
  ctx.session.sender_step = 'ask_message';

  await ctx.reply('✅ Фото получено!\n\n✍️ А теперь напиши своё анонимное послание (текст):`);
});

// --- ОБРАБОТКА ТЕКСТА ---
bot.on('text', async (ctx) => {
  if (!ctx.session) ctx.session = {};
  const text = ctx.message.text;
  
  // Админ-логика
  if (ctx.from.id === ADMIN_ID) {
    if (adminState.waitingForBroadcast) {
      adminState.waitingForBroadcast = false;
      const users = Object.keys(db.users); let sent = 0;
      for (const id of users) { 
          try { await bot.telegram.sendMessage(id, text, { parse_mode: 'HTML' }); sent++; await new Promise(r => setTimeout(r, 50)); } catch(e) {} 
      }
      return ctx.reply(`✅ Рассылка завершена! Отправлено: ${sent}/${users.length}`);
    }
    if (adminState.waitingForPremiumId) {
      adminState.waitingForPremiumId = false;
      const targetId = parseInt(text);
      if (!db.users[targetId]) return ctx.reply('❌ Пользователь не найден.');
      db.users[targetId].is_premium = true; 
      db.users[targetId].premium_expiry = Date.now() + 30*24*60*60*1000;
      scheduleSave();
      return ctx.reply(`✅ Premium выдан пользователю ${db.users[targetId].first_name} (${targetId})`);
    }
  }

  // Шаг 1 для отправителя: Имя
  if (ctx.session.sender_step === 'ask_name') {
    ctx.session.sender_name = text;
    ctx.session.sender_step = 'ask_photo';
    return ctx.reply('📸 Отлично! Теперь отправь <b>своё реальное фото</b> (как картинку). Не бойся, оно зашифровано!', { parse_mode: 'HTML' });
  }

  // Шаг 3 для отправителя: Текст сообщения
  if (ctx.session.sender_step === 'ask_message') {
    const targetId = ctx.session.targetId;
    if (text.length > 200) return ctx.reply('Слишком длинное! Максимум 200 символов.');

    const aura = detectAura(text);
    const msgId = addMessage(targetId, text, ctx.session.sender_name, ctx.session.sender_photo, aura);
    ctx.session = {};

    await ctx.reply('✅ Послание доставлено! Твоё лицо в безопасности 🤫', getMainMenu());
    try {
      await bot.telegram.sendMessage(targetId, '🤫 <b>Тебе пришло новое анонимное послание!</b>', {
        parse_mode: 'HTML',
        reply_markup: Markup.inlineKeyboard([[Markup.button.callback('📨 Прочитать', `read_${msgId}`)]])
      });
    } catch (e) {}
  }
});

// === ЧТЕНИЕ СООБЩЕНИЙ (Текст бесплатно, Фото и Имя - за деньги) ===
bot.action('read_messages', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.answerCbQuery('Сообщений нет!');
  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);
  showNextMessage(ctx);
});

bot.action(/^read_(.+)$/, (ctx) => {
  const msgId = ctx.match[1];
  const msg = getMessageById(parseInt(msgId));
  if (!msg) return ctx.answerCbQuery('Ошибка');
  markAsRead(msg.id);
  
  const user = db.users[ctx.from.id];
  const isVip = user.is_vip && user.vip_expiry > Date.now();
  const isPremium = user.is_premium && user.premium_expiry > Date.now();
  const hasAccess = isPremium || (isVip && user.reveal_credits > 0) || msg.reveal_bought;

  if (hasAccess) {
    if (isVip && !isPremium) { user.reveal_credits--; scheduleSave(); }
    ctx.answerCbQuery();
    ctx.replyWithPhoto(msg.sender_photo, {
      caption: `🤫 <b>Анонимное сообщение:</b>\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n🕵️ <b>Разоблачение:</b> ${msg.sender_name}`,
      parse_mode: 'HTML'
    });
  } else {
    ctx.answerCbQuery();
    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n<i>Хочешь увидеть лицо и узнать имя автора? 📸</i>`,
      { parse_mode: 'HTML', ...Markup.inlineKeyboard([
        [Markup.button.callback('📸 Открыть фото и имя (149₽)', `buy_reveal_${msg.id}`)],
        [Markup.button.callback('➡️ Далее', 'skip_msg')]
      ])}
    );
  }
});

function showNextMessage(ctx) {
  if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Все сообщения прочитаны!', { reply_markup: getMainMenu() });
  const msgId = ctx.session.msgQueue.shift();
  const msg = getMessageById(msgId);
  if (!msg) return showNextMessage(ctx);
  markAsRead(msg.id);

  const user = db.users[ctx.from.id];
  const isVip = user.is_vip && user.vip_expiry > Date.now();
  const isPremium = user.is_premium && user.premium_expiry > Date.now();
  const hasAccess = isPremium || (isVip && user.reveal_credits > 0) || msg.reveal_bought;

  if (hasAccess) {
    if (isVip && !isPremium) { user.reveal_credits--; scheduleSave(); }
    ctx.replyWithPhoto(msg.sender_photo, {
      caption: `🤫 <b>Анонимное сообщение:</b>\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n🕵️ <b>Разоблачение:</b> ${msg.sender_name}`,
      parse_mode: 'HTML'
    });
    return showNextMessage(ctx);
  } else {
    ctx.reply(
      `🤫 <b>Анонимное сообщение:</b>\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n<i>Лицо отправителя скрыто 📸</i>`,
      { parse_mode: 'HTML', ...Markup.inlineKeyboard([
        [Markup.button.callback('📸 Открыть фото и имя (149₽)', `buy_reveal_${msg.id}`)],
        [Markup.button.callback('➡️ Далее', 'skip_msg')]
      ])}
    );
  }
}

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });

// === ИНЛАЙНЫ МАГАЗИНА ===
bot.action('shop_reveal', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(`📸 <b>Открыть фото и имя</b>\nУзнай, кто скрывается за анонимкой!\n\n<b>149 ₽</b>`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_0`))], 
            [Markup.button.callback('✅ Я оплатил', 'check_reveal_0')]
        ]) 
    }); 
});

bot.action('shop_vip', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(`💎 <b>VIP Статус (1 месяц)</b>\n✅ 5 бесплатных открытий фото\n✅ Значок 💎\n\n<b>399 ₽</b>`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.url('💳 Оплатить VIP', generatePaymentLink(399, `${ctx.from.id}_vip`))], 
            [Markup.button.callback('✅ Я оплатил VIP', 'check_vip')]
        ]) 
    }); 
});

bot.action('shop_premium', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(`👑 <b>PREMIUM Статус (1 месяц)</b>\n✅ Безлимитное открытие ВСЕХ фото навсегда\n✅ Значок 👑\n\n<b>799 ₽</b>`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.url('💳 Оплатить PREMIUM', generatePaymentLink(799, `${ctx.from.id}_premium`))], 
            [Markup.button.callback('✅ Я оплатил PREMIUM', 'check_premium')]
        ]) 
    }); 
});

bot.action(/^buy_reveal_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    ctx.answerCbQuery(); 
    ctx.reply(`📸 <b>Открыть фото</b> (149₽)`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${id}`))], 
            [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${id}`)]
        ]) 
    }); 
});

// === ПРОВЕРКА ОПЛАТЫ ===
bot.action('check_vip', async (ctx) => { 
    await ctx.answerCbQuery('Проверяю...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_vip`)) { 
        const u = db.users[ctx.from.id]; 
        u.is_vip = true; 
        u.vip_expiry = Date.now() + 30*24*60*60*1000; 
        u.reveal_credits = 5; 
        scheduleSave(); 
        ctx.reply('💎 VIP активирован! У тебя 5 бесплатных открытий фото.', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Не найдено'); } 
});

bot.action('check_premium', async (ctx) => { 
    await ctx.answerCbQuery('Проверяю...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_premium`)) { 
        const u = db.users[ctx.from.id]; 
        u.is_premium = true; 
        u.premium_expiry = Date.now() + 30*24*60*60*1000; 
        scheduleSave(); 
        ctx.reply('👑 PREMIUM активирован! Ты видишь все лица бесплатно!', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Не найдено'); } 
});

bot.action('check_reveal_0', async (ctx) => { 
    await ctx.answerCbQuery('Проверяю...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_reveal_0`)) { 
        const m = Object.values(db.messages).find(m => m.target_id === ctx.from.id && !m.is_read); 
        if(m) {
            m.reveal_bought = true; 
            scheduleSave(); 
            ctx.replyWithPhoto(m.sender_photo, {caption: `🕵️ <b>Разоблачение:</b> ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'});
        } 
    } else { ctx.reply('❌ Не найдено'); } 
});

bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    await ctx.answerCbQuery('Проверяю...'); 
    if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${id}`)){ 
        const m = getMessageById(parseInt(id)); 
        if(m) {
            m.reveal_bought = true; 
            scheduleSave(); 
            ctx.replyWithPhoto(m.sender_photo, {caption: `🕵️ <b>Разоблачение:</b> ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'});
        } 
    } else { ctx.reply('❌ Не найдено'); } 
});

// =====================================================================
// === АДМИН-ПАНЕЛЬ ===
// =====================================================================
bot.command('admin', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    ctx.reply('👑 <b>Админ-панель</b>', { parse_mode: 'HTML', ...Markup.inlineKeyboard([
        [Markup.button.callback('📊 Статистика', 'admin_stats')],
        [Markup.button.callback('📢 Рассылка', 'admin_broadcast')],
        [Markup.button.callback('👑 Выдать Premium', 'admin_grant_premium')],
        [Markup.button.callback('🧹 Очистить базу', 'admin_clear_msgs')]
    ])});
});

bot.action('admin_stats', async (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    await ctx.answerCbQuery(); 
    const u = Object.keys(db.users).length; 
    const m = Object.keys(db.messages).length; 
    const p = Object.values(db.users).filter(u => u.is_premium && u.premium_expiry > Date.now()).length; 
    ctx.reply(`📊 Статистика:\n\n👥 Юзеров: <b>${u}</b>\n👑 Premium: <b>${p}</b>\n📬 Сообщений в базе: <b>${m}</b>`, {parse_mode:'HTML'}); 
});

bot.action('admin_broadcast', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    ctx.answerCbQuery(); 
    adminState.waitingForBroadcast = true; 
    ctx.reply('📢 Отправьте текст для рассылки:'); 
});

bot.action('admin_grant_premium', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    ctx.answerCbQuery(); 
    adminState.waitingForPremiumId = true; 
    ctx.reply('👑 Отправьте Telegram ID:'); 
});

bot.action('admin_clear_msgs', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    ctx.answerCbQuery(); 
    const c = Object.keys(db.messages).length; 
    db.messages = {}; 
    scheduleSave(); 
    ctx.reply(`🧹 Удалено ${c} сообщений!`); 
});

// === ЗАПУСК ===
bot.launch().then(() => console.log('🤖 Бот "Шёпот" (NGL + Фото) запущен!')).catch(err => console.error(err));
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
