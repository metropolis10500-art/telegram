require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

const BOT_TOKEN = process.env.BOT_TOKEN;
const YOOMONEY_WALLET = process.env.YOOMONEY_WALLET;
const YOOMONEY_API_TOKEN = process.env.YOOMONEY_API_TOKEN;
const ADMIN_ID = parseInt(process.env.ADMIN_ID);
const DB_FILE = './database.json';

const bot = new Telegraf(BOT_TOKEN);

// === БАЗА ДАННЫХ ===
let db = { users: {}, messages: {} };
if (fs.existsSync(DB_FILE)) {
    try {
        const loadedData = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        db.users = loadedData.users || {};
        if (Array.isArray(loadedData.messages)) { loadedData.messages.forEach(m => db.messages[m.id] = m); } 
        else { db.messages = loadedData.messages || {}; }
    } catch (e) { console.error('Ошибка БД:', e); }
}

let saveTimeout = null;
function scheduleSave() {
    if (!saveTimeout) {
        saveTimeout = setTimeout(() => { fs.writeFile(DB_FILE, JSON.stringify(db, null, 2), (err) => { if (err) console.error(err); }); saveTimeout = null; }, 2000);
    }
}

// Очистка старых сообщений
setInterval(() => {
    const threeDaysAgo = Date.now() - 3 * 24 * 60 * 60 * 1000;
    let deletedCount = 0;
    Object.keys(db.messages).forEach(id => { if (db.messages[id].is_read && db.messages[id].id < threeDaysAgo) { delete db.messages[id]; deletedCount++; } });
    if (deletedCount > 0) { console.log(`Удалено ${deletedCount} старых сообщений`); scheduleSave(); }
}, 3600000);

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    if (!db.users[tg_id]) { 
        db.users[tg_id] = { username, first_name, is_premium: false, premium_expiry: 0, ref_count: 0, invited_by: null }; 
        scheduleSave(); 
    }
}

function addMessage(target_id, text, sender_name, sender_photo) { 
    const id = Date.now(); 
    db.messages[id] = { id, target_id, text, sender_name, sender_photo, is_read: false, is_revealed: false }; 
    scheduleSave(); 
    return id; 
}

function getUnreadMessages(target_id) { 
    return Object.values(db.messages).filter(m => m.target_id === target_id && !m.is_read).sort((a, b) => b.id - a.id); 
}

function getMessageById(id) { return db.messages[id]; }
function markAsRead(id) { const m = db.messages[id]; if (m) { m.is_read = true; scheduleSave(); } }
function revealMessage(id) { const m = db.messages[id]; if (m) { m.is_revealed = true; scheduleSave(); } }

// === УТИЛИТЫ ===
function getMainMenu() { 
    return Markup.keyboard([
        ['📬 Сообщения', '🔗 Моя ссылка'], 
        ['💎 Премиум', '👤 Профиль']
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

  // Вход по реферальной ссылке
  if (payload && payload.startsWith('r_')) {
    const refId = parseInt(payload.replace('r_', ''));
    if (refId !== userId && db.users[refId]) {
        if (!db.users[userId].invited_by) {
            db.users[userId].invited_by = refId;
            db.users[refId].ref_count++;
            scheduleSave();
            bot.telegram.sendMessage(refId, '👥 По твоей ссылке перешел друг! Чем больше переходов, тем круче твой профиль.').catch(()=>{});
        }
    }
    return ctx.reply('👋 Добро пожаловать! Тебя пригласили в Шёпот. Кидай свою ссылку и жди анонимок!', { parse_mode: 'HTML', ...getMainMenu() });
  }

  // Вход для отправки сообщения
  if (payload && payload.startsWith('w_')) {
    const targetId = parseInt(payload.replace('w_', ''));
    const targetUser = db.users[targetId];
    if (!targetUser) return ctx.reply('Этот человек еще не в Шёпоте :(');
    
    ctx.session = { targetId: targetId, sender_step: 'ask_name' };
    return ctx.reply(
      `🤫 <b>Напиши анонимное сообщение для ${targetUser.first_name}</b>\n\n` +
      `Правило Шёпота: укажи свое имя и фото. Получатель прочтет текст бесплатно, но твое лицо будет скрыто, пока он не оплатит его раскрытие!\n\n` +
      `👤 Напиши свое имя:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  }

  // Обычный вход
  ctx.session = {};
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
  const user = db.users[userId];
  const badge = user.is_premium ? '👑' : '';
  
  await ctx.reply(
    `👋 <b>Добро пожаловать в Шёпот, ${badge} ${ctx.from.first_name}!</b> 🤫\n\n` +
    `Это место, где ты получаешь анонимные сообщения и вопросы.\n\n` +
    `📱 Кидай ссылку в Instagram, TikTok или VK. Друзья напишут то, что никогда не сказали бы в лицо!\n\n` +
    `📩 Тексты ты читаешь <b>бесплатно</b>.\n` +
    `🎭 Но авторы скрыты. Хочешь узнать, кто это и увидеть фото? Это доступно в Премиум!\n\n` +
    `🔗 <b>Твоя ссылка:</b>\n<code>${link}</code>`,
    { parse_mode: 'HTML', ...getMainMenu() }
  );
});

// --- КНОПКИ МЕНЮ ---
bot.hears('🔗 Моя ссылка', (ctx) => {
  const userId = ctx.from.id;
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
  const refLink = `https://t.me/${ctx.botInfo.username}?start=r_${userId}`;
  ctx.reply(
    `🔗 <b>Ссылка для соцсетей:</b>\n<code>${link}</code>\n\n` +
    `👥 <b>Реферальная ссылка:</b>\n<code>${refLink}</code>\n\nКидай первую ссылку в Stories!`,
    { parse_mode: 'HTML' }
  );
});

bot.hears('📬 Сообщения', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 Пока пусто... Поделись ссылкой, чтобы получать анонимки!');
  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);
  showNextMessage(ctx);
});

bot.hears('💎 Премиум', (ctx) => {
  ctx.reply(
    `🎭 <b>Хочешь знать, кто тебе пишет?</b>\n\nВсе авторы скрыты. Выбери, как их раскрыть:`,
    { 
      parse_mode: 'HTML', 
      ...Markup.inlineKeyboard([
        [Markup.button.callback('🕵️ Раскрыть 1 автора (149 ₽)', 'shop_reveal')],
        [Markup.button.callback('👑 Премиум навсегда (799 ₽)', 'shop_premium')]
      ])
    }
  );
});

bot.hears('👤 Профиль', (ctx) => {
  const user = db.users[ctx.from.id];
  const premiumStatus = (user.is_premium && user.premium_expiry > Date.now()) ? '👑 Активен' : '❌ Нет';
  ctx.reply(
    `👤 <b>Мой профиль</b>\n\n🤫 Имя: <b>${ctx.from.first_name}</b>\n👑 Премиум: ${premiumStatus}\n👥 Переходов по рефке: <b>${user.ref_count}</b>`,
    { parse_mode: 'HTML' }
  );
});

// --- ОБРАБОТКА ФОТО И ТЕКСТА ---
bot.on('photo', async (ctx) => {
  if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
  const photoId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
  ctx.session.sender_photo = photoId;
  ctx.session.sender_step = 'ask_message';
  await ctx.reply('✅ Фото получено! Теперь напиши послание (текст):');
});

bot.on('text', async (ctx) => {
  if (!ctx.session) ctx.session = {};
  const text = ctx.message.text;
  
  // Админ
  if (ctx.from.id === ADMIN_ID) {
    if (adminState.waitingForBroadcast) {
      adminState.waitingForBroadcast = false;
      const users = Object.keys(db.users); let sent = 0;
      for (const id of users) { try { await bot.telegram.sendMessage(id, text, { parse_mode: 'HTML' }); sent++; await new Promise(r => setTimeout(r, 50)); } catch(e) {} }
      return ctx.reply(`✅ Отправлено: ${sent}/${users.length}`);
    }
    if (adminState.waitingForPremiumId) {
      adminState.waitingForPremiumId = false;
      const targetId = parseInt(text);
      if (!db.users[targetId]) return ctx.reply('❌ Не найден.');
      db.users[targetId].is_premium = true; db.users[targetId].premium_expiry = Date.now() + 30*24*60*60*1000; scheduleSave();
      return ctx.reply(`✅ Premium выдан!`);
    }
  }

  // Шаг 1: Имя отправителя
  if (ctx.session.sender_step === 'ask_name') {
    ctx.session.sender_name = text;
    ctx.session.sender_step = 'ask_photo';
    return ctx.reply('📸 Прикрепи свое фото (картинкой). Оно будет скрыто за маской!');
  }

  // Шаг 3: Текст послания
  if (ctx.session.sender_step === 'ask_message') {
    const targetId = ctx.session.targetId;
    if (text.length > 200) return ctx.reply('Максимум 200!');
    const msgId = addMessage(targetId, text, ctx.session.sender_name, ctx.session.sender_photo);

    ctx.session = {};
    await ctx.reply('✅ Послание доставлено! Твое лицо в безопасности 🤫', getMainMenu());
    try {
      await bot.telegram.sendMessage(targetId, '🤫 <b>Тебе пришло новое анонимное послание!</b>', { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.callback('📬 Прочитать', `read_${msgId}`)]
        ])
      });
    } catch (e) {}
  }
});

// === ЧТЕНИЕ СООБЩЕНИЙ (Текст БЕСПЛАТНО, Автор ПЛАТНО) ===
bot.action('read_messages', (ctx) => { 
  const msgs = getUnreadMessages(ctx.from.id); 
  if (msgs.length === 0) return ctx.answerCbQuery('Пусто!'); 
  ctx.session = ctx.session || {}; 
  ctx.session.msgQueue = msgs.map(m => m.id); 
  showNextMessage(ctx); 
});

bot.action(/^read_(.+)$/, (ctx) => { 
  const msgId = ctx.match[1]; 
  const msg = getMessageById(parseInt(msgId)); 
  if (!msg) return ctx.answerCbQuery('Ошибка'); 
  markAsRead(msg.id); 
  showSingleMessage(ctx, msg);
});

function showNextMessage(ctx) { 
  if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Всё прочитано!', { reply_markup: getMainMenu() }); 
  const msgId = ctx.session.msgQueue.shift(); 
  const msg = getMessageById(msgId); 
  if (!msg) return showNextMessage(ctx); 
  markAsRead(msg.id); 
  showSingleMessage(ctx, msg);
}

function showSingleMessage(ctx, msg) {
  const user = db.users[ctx.from.id]; 
  const isPremium = user.is_premium && user.premium_expiry > Date.now(); 
  const hasAccess = isPremium || msg.is_revealed;

  if (hasAccess) { 
    if (!msg.is_revealed) { revealMessage(msg.id); }
    ctx.answerCbQuery(); 
    ctx.replyWithPhoto(msg.sender_photo, { 
      caption: `📩 <b>Послание:</b>\n"${msg.text}"\n\n🎭 <b>Автор раскрыт:</b> ${msg.sender_name}`, 
      parse_mode: 'HTML' 
    }); 
  } else { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `📩 <b>Анонимное послание:</b>\n"${msg.text}"\n\n🎭 <i>Автор скрыт. Хочешь узнать, кто это и увидеть фото?</i>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.callback('🕵️ Раскрыть автора (149 ₽)', `buy_reveal_${msg.id}`)],
          [Markup.button.callback('👑 Купить Премиум', 'shop_premium'), Markup.button.callback('➡️ Далее', 'skip_msg')]
        ]) 
      }
    ); 
  }
}

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });

// === МАГАЗИН (ПОДРОБНОЕ ОПИСАНИЕ) ===
bot.action('shop_reveal', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `🕵️ <b>Раскрыть 1 автора</b>\n\nЧто дает: Ты узнаешь имя и увидишь фото человека, написавшего тебе послание.\n\nСтоимость: <b>149 ₽</b>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_0`))], 
          [Markup.button.callback('✅ Я оплатил', 'check_reveal_0')]
        ]) 
      }
    ); 
});

bot.action('shop_premium', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `👑 <b>Премиум навсегда</b>\n\nЧто дает:\n✅ Все авторы раскрываются автоматически (без доплат)\n✅ Значок 👑 в профиле\n\nСтоимость: <b>799 ₽</b>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_premium`))], 
          [Markup.button.callback('✅ Я оплатил', 'check_premium')]
        ]) 
      }
    ); 
});

bot.action(/^buy_reveal_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    ctx.answerCbQuery(); 
    ctx.reply(
      `🕵️ <b>Раскрыть автора (149 ₽)</b>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${id}`))], 
          [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${id}`)]
        ]) 
      }
    ); 
});

// === ОПЛАТЫ ===
bot.action('check_premium', async (ctx) => { 
    await ctx.answerCbQuery('Проверяю...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_premium`)) { 
        const u=db.users[ctx.from.id]; u.is_premium=true; u.premium_expiry=Date.now()+100*365*24*60*60*1000; scheduleSave(); ctx.reply('👑 Премиум активирован навсегда! Все маски сняты.', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Оплата не найдена. Попробуй позже.'); } 
});

bot.action('check_reveal_0', async (ctx) => { 
    await ctx.answerCbQuery('Проверяю...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_reveal_0`)) { 
        const m = Object.values(db.messages).find(m => m.target_id === ctx.from.id && !m.is_revealed);
        if(m) { revealMessage(m.id); ctx.replyWithPhoto(m.sender_photo, { caption: `🎭 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}); }
        else { ctx.reply('🔑 Оплата прошла, но неоплаченных посланий нет!'); }
    } else { ctx.reply('❌ Оплата не найдена.'); } 
});

bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    await ctx.answerCbQuery('Проверяю...'); 
    if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${id}`)){ 
        const m = getMessageById(parseInt(id)); 
        if(m) { revealMessage(m.id); ctx.replyWithPhoto(m.sender_photo, { caption: `🎭 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}); }
    } else { ctx.reply('❌ Оплата не найдена.'); } 
});

// === АДМИНКА ===
bot.command('admin', async (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    ctx.reply('👑 Админка', { 
      parse_mode: 'HTML', 
      ...Markup.inlineKeyboard([
        [Markup.button.callback('📊 Стат', 'admin_stats')], 
        [Markup.button.callback('📢 Рассылка', 'admin_broadcast')], 
        [Markup.button.callback('👑 Premium', 'admin_grant_premium')], 
        [Markup.button.callback('🧹 Очистить', 'admin_clear_msgs')]
      ]) 
    }); 
});

bot.action('admin_stats', async (ctx) => { if (ctx.from.id !== ADMIN_ID) return; await ctx.answerCbQuery(); const u=Object.keys(db.users).length; const m=Object.keys(db.messages).length; ctx.reply(`📊:\n👥 ${u}\n📬 ${m}`, {parse_mode:'HTML'}); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); adminState.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); adminState.waitingForPremiumId=true; ctx.reply('👑 ID:'); });
bot.action('admin_clear_msgs', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); const c=Object.keys(db.messages).length; db.messages={}; scheduleSave(); ctx.reply(`🧹 ${c}!`); });

bot.launch().then(() => console.log('🤖 Шёпот запущен!')).catch(err => console.error(err));
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
