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

setInterval(() => {
    const threeDaysAgo = Date.now() - 3 * 24 * 60 * 60 * 1000;
    let deletedCount = 0;
    Object.keys(db.messages).forEach(id => { if (db.messages[id].is_read && db.messages[id].id < threeDaysAgo) { delete db.messages[id]; deletedCount++; } });
    if (deletedCount > 0) { console.log(`Удалено ${deletedCount} старых сообщений`); scheduleSave(); }
}, 3600000);

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    if (!db.users[tg_id]) { 
        db.users[tg_id] = { 
            username, first_name, 
            is_vip: false, vip_expiry: 0, is_premium: false, premium_expiry: 0, reveal_credits: 0, 
            // Новые поля для геймификации
            last_spin_time: 0, free_keys: 0, ref_count: 0, aura_score: 0, aura_title: "Новичок"
        }; 
        scheduleSave(); 
    }
}

function addMessage(target_id, text, sender_name, sender_photo, aura) { 
    const id = Date.now(); 
    db.messages[id] = { id, target_id, text, sender_name, sender_photo, aura, is_read: false, reveal_bought: false }; 
    scheduleSave(); return id; 
}

function getUnreadMessages(target_id) { return Object.values(db.messages).filter(m => m.target_id === target_id && !m.is_read).sort((a, b) => b.id - a.id); }
function getMessageById(id) { return db.messages[id]; }
function markAsRead(id) { const m = db.messages[id]; if (m) { m.is_read = true; scheduleSave(); } }

// === УТИЛИТЫ ===
function detectAura(text) { const t = text.toLowerCase(); if (t.match(/люблю|нрав|красив|горяч/)) return "🔥 Пылкая"; if (t.match(/ненави|дурак|туп/)) return "⚡ Грозовая"; if (t.match(/скуч|грус/)) return "🌧 Туманная"; return "🌙 Лунная"; }

function updateAuraTitle(user) {
    if (user.aura_score >= 50) user.aura_title = "🎭 Магистр Маскарада";
    else if (user.aura_score >= 20) user.aura_title = "💀 Лорд Тайн";
    else if (user.aura_score >= 10) user.aura_title = "👁 Искатель";
    else if (user.aura_score >= 5) user.aura_title = "🦇 Блуждающий";
    else user.aura_title = "🌑 Новичок";
    scheduleSave();
}

function getMainMenu() { 
    return Markup.keyboard([
        ['📨 Сообщения', '🎡 Фортуна'], 
        ['🔗 Моя ссылка', '🎭 Магазин']
    ]).resize(); 
}

function generatePaymentLink(amount, label) { return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=small&paymentType=AC&sum=${amount}&label=${label}`; }
async function checkYooMoneyPayment(label) { try { const p = new URLSearchParams(); p.append('label', label); p.append('type', 'in'); const r = await fetch('https://yoomoney.ru/api/operation-history', { method: 'POST', headers: { 'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: p.toString() }); const d = await r.json(); return d.operations && d.operations.some(o => o.status === 'success'); } catch (e) { return false; } }

let adminState = {};

// =====================================================================
// === ЛОГИКА БОТА ===
// =====================================================================

bot.start(async (ctx) => {
  const userId = ctx.from.id;
  registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Аноним');
  const payload = ctx.startPayload;

  // ВХОД ПО РЕФЕРАЛЬНОЙ ССЫЛКЕ
  if (payload && payload.startsWith('r_')) {
    const refId = parseInt(payload.replace('r_', ''));
    if (refId !== userId && db.users[refId]) {
        if (!db.users[userId].referred_by) {
            db.users[userId].referred_by = refId;
            db.users[refId].ref_count++;
            // Награда за 3 друзей
            if (db.users[refId].ref_count % 3 === 0) {
                db.users[refId].free_keys++;
                bot.telegram.sendMessage(refId, '🎉 Твой друг перешел по ссылке! Ты получил 1 бесплатный Ключ Маскарада! (Пригласи еще 2 друзей для следующего)').catch(()=>{});
            } else {
                bot.telegram.sendMessage(refId, '👥 Новый друг на балу! Осталось пригласить ' + (3 - (db.users[refId].ref_count % 3)) + ' чел. для Ключа.').catch(()=>{});
            }
            scheduleSave();
        }
    }
    // Показываем обычное приветствие после учета реферала
    return ctx.reply('🎭 Добро пожаловать на бал! Твой друг пригласил тебя. Кидай свою ссылку в соцсети и читай тайны!', { parse_mode: 'HTML', ...getMainMenu() });
  }

  // ВХОД ДЛЯ ОТПРАВКИ СООБЩЕНИЯ
  if (payload && payload.startsWith('w_')) {
    const targetId = parseInt(payload.replace('w_', ''));
    const targetUser = db.users[targetId];
    if (!targetUser) return ctx.reply('Этот человек еще не на нашем балу :(');
    
    ctx.session = { targetId: targetId, sender_step: 'ask_name' };
    return ctx.reply(
      `🎭 <b>Оставь тайное послание для ${targetUser.first_name}</b>\n\nНапиши свое имя и прикрепи фото. Твоя личность останется в секрете за маской!\n\n👤 Как тебя зовут:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  }

  // ОБЫЧНЫЙ ВХОД
  ctx.session = {};
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
  const refLink = `https://t.me/${ctx.botInfo.username}?start=r_${userId}`;
  const user = db.users[userId];
  const badge = user.is_premium ? '👑' : (user.is_vip ? '💎' : '');
  
  await ctx.reply(
    `👋 <b>Добро пожаловать на бал, ${badge} ${ctx.from.first_name}!</b>\n\n` +
    `🎭 Твоя аура: <b>${user.aura_title}</b> (Очков: ${user.aura_score})\n🔑 Бесплатных ключей: <b>${user.free_keys}</b>\n\n` +
    `📱 Кидай ссылку в соцсети. Люди будут писать тайны.\n🎭 Все авторы в масках. Хочешь узнать кто? Крути Фортуна или покупай ключи!\n👥 Пригласи 3 друзей по рефке — получи ключ бесплатно!`,
    { parse_mode: 'HTML', ...getMainMenu() }
  );
});

// --- КНОПКИ МЕНЮ ---
bot.hears('📨 Сообщения', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 Нет сообщений. Поделись ссылкой!');
  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);
  showNextMessage(ctx);
});

bot.hears('🔗 Моя ссылка', (ctx) => {
  const userId = ctx.from.id;
  const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
  const refLink = `https://t.me/${ctx.botInfo.username}?start=r_${userId}`;
  ctx.reply(
    `🔗 <b>Ссылка для соцсетей:</b>\n<code>${link}</code>\n\n` +
    `👥 <b>Реферальная ссылка (для ключей):</b>\n<code>${refLink}</code>\n\nКаждые 3 друга = 1 бесплатный Ключ Маскарада!`,
    { parse_mode: 'HTML' }
  );
});

bot.hears('🎡 Фортуна', (ctx) => {
  const user = db.users[ctx.from.id];
  const now = Date.now();
  const hours24 = 24 * 60 * 60 * 1000;

  if (now - user.last_spin_time < hours24) {
    const timeLeft = Math.ceil((hours24 - (now - user.last_spin_time)) / (60 * 60 * 1000));
    return ctx.reply(`⏳ Колесо Фортуны отдыхает.\n\nСледующий спин через <b>${timeLeft} ч.</b>\nНе хочешь ждать? Загляни в Магазин!`, { parse_mode: 'HTML' });
  }

  ctx.reply('🎡 <b>Колесо Фортуны!</b>\n\nТы можешь крутить колесо раз в сутки. Выпадет ключ или аура!', {
    parse_mode: 'HTML',
    ...Markup.inlineKeyboard([[Markup.button.callback('🎡 Крутить!', 'spin_wheel')]])
  });
});

bot.hears('🎭 Магазин', (ctx) => {
  const user = db.users[ctx.from.id];
  ctx.reply(
    `🎭 <b>Магазин Маскарада</b>\n\n🔑 У тебя ключей: <b>${user.free_keys}</b>`,
    { parse_mode: 'HTML', ...Markup.inlineKeyboard([
      [Markup.button.callback('🎭 Снять маску (1 Ключ)', 'use_key')],
      [Markup.button.callback('🔑 Купить 1 Ключ (149 ₽)', 'shop_reveal')],
      [Markup.button.callback('💎 VIP — 5 ключей (399 ₽)', 'shop_vip')],
      [Markup.button.callback('👑 PREMIUM — Безлимит (799 ₽)', 'shop_premium')]
    ])}
  );
});

// --- ОБРАБОТКА ФОТО И ТЕКСТА ---
bot.on('photo', async (ctx) => {
  if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
  const photoId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
  ctx.session.sender_photo = photoId;
  ctx.session.sender_step = 'ask_message';
  await ctx.reply('✅ Фото в маске! Теперь напиши послание (текст):');
});

bot.on('text', async (ctx) => {
  if (!ctx.session) ctx.session = {};
  const text = ctx.message.text;
  
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

  if (ctx.session.sender_step === 'ask_name') {
    ctx.session.sender_name = text;
    ctx.session.sender_step = 'ask_photo';
    return ctx.reply('📸 Прикрепи фото (картинкой). Оно будет скрыто!');
  }

  if (ctx.session.sender_step === 'ask_message') {
    const targetId = ctx.session.targetId;
    if (text.length > 200) return ctx.reply('Максимум 200!');
    const aura = detectAura(text);
    const msgId = addMessage(targetId, text, ctx.session.sender_name, ctx.session.sender_photo, aura);
    
    // Начисляем ауру получателю
    db.users[targetId].aura_score++;
    updateAuraTitle(db.users[targetId]);

    ctx.session = {};
    await ctx.reply('✅ Тайна доставлена! Маска на месте 🎭', getMainMenu());
    try {
      await bot.telegram.sendMessage(targetId, '🤫 <b>Новая тайна от незнакомца!</b>', { parse_mode: 'HTML', reply_markup: Markup.inlineKeyboard([[Markup.button.callback('📨 Читать', `read_${msgId}`)]]) });
    } catch (e) {}
  }
});

// === ЧТЕНИЕ ===
bot.action('read_messages', (ctx) => { const msgs = getUnreadMessages(ctx.from.id); if (msgs.length === 0) return ctx.answerCbQuery('Пусто!'); ctx.session = ctx.session || {}; ctx.session.msgQueue = msgs.map(m => m.id); showNextMessage(ctx); });

bot.action(/^read_(.+)$/, (ctx) => { const msgId = ctx.match[1]; const msg = getMessageById(parseInt(msgId)); if (!msg) return ctx.answerCbQuery('Ошибка'); markAsRead(msg.id); const user = db.users[ctx.from.id]; const isVip = user.is_vip && user.vip_expiry > Date.now(); const isPremium = user.is_premium && user.premium_expiry > Date.now(); const hasAccess = isPremium || (isVip && user.reveal_credits > 0) || msg.reveal_bought || user.free_keys > 0;
  if (hasAccess) { if (isVip && !isPremium) { user.reveal_credits--; } else if (!msg.reveal_bought && !isPremium) { user.free_keys--; } scheduleSave(); ctx.answerCbQuery(); ctx.replyWithPhoto(msg.sender_photo, { caption: `🤫 Послание:\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n🎭 <b>Маска снята:</b> ${msg.sender_name}`, parse_mode: 'HTML' }); } else { ctx.answerCbQuery(); ctx.reply(`🤫 Послание:\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n<i>🎭 Автор в маске. Используй Ключ!</i>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🎭 Исп. Ключ', `use_key_${msg.id}`), Markup.button.callback('🔑 Купить ключ', `buy_reveal_${msg.id}`)], [Markup.button.callback('➡️ Далее', 'skip_msg')]] }); }
});

function showNextMessage(ctx) { if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Конец!', { reply_markup: getMainMenu() }); const msgId = ctx.session.msgQueue.shift(); const msg = getMessageById(msgId); if (!msg) return showNextMessage(ctx); markAsRead(msg.id); const user = db.users[ctx.from.id]; const isVip = user.is_vip && user.vip_expiry > Date.now(); const isPremium = user.is_premium && user.premium_expiry > Date.now(); const hasAccess = isPremium || (isVip && user.reveal_credits > 0) || msg.reveal_bought || user.free_keys > 0;
  if (hasAccess) { if (isVip && !isPremium) { user.reveal_credits--; } else if (!msg.reveal_bought && !isPremium) { user.free_keys--; } scheduleSave(); ctx.replyWithPhoto(msg.sender_photo, { caption: `🤫 Послание:\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n🎭 <b>Маска снята:</b> ${msg.sender_name}`, parse_mode: 'HTML' }); return showNextMessage(ctx); } else { ctx.reply(`🤫 Послание:\n📊 Аура: <b>${msg.aura}</b>\n\n"${msg.text}"\n\n<i>🎭 Автор в маске.</i>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🎭 Исп. Ключ', `use_key_${msg.id}`), Markup.button.callback('🔑 Купить', `buy_reveal_${msg.id}`)], [Markup.button.callback('➡️ Далее', 'skip_msg')]] }); }
}
bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });

// === ИСПОЛЬЗОВАНИЕ КЛЮЧЕЙ ===
bot.action('use_key', (ctx) => { const user = db.users[ctx.from.id]; if (user.free_keys <= 0) return ctx.answerCbQuery('Нет ключей!'); const m = getUnreadMessages(ctx.from.id)[0]; if(!m) return ctx.answerCbQuery('Нет сообщений!'); user.free_keys--; m.reveal_bought = true; scheduleSave(); ctx.answerCbQuery(); ctx.replyWithPhoto(m.sender_photo, { caption: `🎭 Маска снята: ${m.sender_name}\n\n"${m.text}"`, parse_mode: 'HTML' }); });
bot.action(/^use_key_(.+)$/, (ctx) => { const id = ctx.match[1]; const user = db.users[ctx.from.id]; if (user.free_keys <= 0) return ctx.answerCbQuery('Нет ключей!'); const m = getMessageById(parseInt(id)); if(!m) return ctx.answerCbQuery('Ошибка'); user.free_keys--; m.reveal_bought = true; scheduleSave(); ctx.answerCbQuery(); ctx.replyWithPhoto(m.sender_photo, { caption: `🎭 Маска снята: ${m.sender_name}\n\n"${m.text}"`, parse_mode: 'HTML' }); });

// === КОЛЕСО ФОРТУНЫ ===
bot.action('spin_wheel', (ctx) => { const user = db.users[ctx.from.id]; const now = Date.now(); if (now - user.last_spin_time < 24*60*60*1000) return ctx.answerCbQuery('Рано!'); user.last_spin_time = now; const rand = Math.random(); let prize = ''; if (rand < 0.15) { user.free_keys++; prize = '🔑 Ты выиграл 1 Ключ Маскарада!'; } else if (rand < 0.35) { user.aura_score += 5; prize = '✨ Твоя аура усилилась (+5 очков)!'; } else if (rand < 0.55) { user.free_keys++; prize = '🔑 Ты выиграл 1 Ключ Маскарада!'; } else { user.aura_score += 2; prize = '🌙 Твоя аура немного усилилась (+2 очка)'; } updateAuraTitle(user); scheduleSave(); ctx.answerCbQuery(); ctx.reply(`🎡 <b>Колесо Фортуны!</b>\n\n${prize}\n🎭 Твой ранг: <b>${user.aura_title}</b> (Очков: ${user.aura_score})\n🔑 Ключей: ${user.free_keys}`, { parse_mode: 'HTML' }); });

// === МАГАЗИН ===
bot.action('shop_reveal', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🔑 <b>1 Ключ Маскарада</b>\nОткроет личность одного автора.\n\n<b>149 ₽</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_0`))], [Markup.button.callback('✅ Я оплатил', 'check_reveal_0')]]) }); });
bot.action('shop_vip', (ctx) => { ctx.answerCbQuery(); ctx.reply(`💎 <b>VIP</b>\n5 ключей + значок.\n\n<b>399 ₽</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(399, `${ctx.from.id}_vip`))], [Markup.button.callback('✅ Я оплатил', 'check_vip')]]) }); });
bot.action('shop_premium', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>PREMIUM</b>\nБезлимит ключей + ежедневные бонусы.\n\n<b>799 ₽</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_premium`))], [Markup.button.callback('✅ Я оплатил', 'check_premium')]]) }); });
bot.action(/^buy_reveal_(.+)$/, async (ctx) => { const id = ctx.match[1]; ctx.answerCbQuery(); ctx.reply(`🔑 Купить Ключ (149₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${id}`))], [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${id}`)]) }); });

// === ОПЛАТЫ ===
bot.action('check_vip', async (ctx) => { await ctx.answerCbQuery('Проверка...'); if (await checkYooMoneyPayment(`${ctx.from.id}_vip`)) { const u=db.users[ctx.from.id]; u.is_vip=true; u.vip_expiry=Date.now()+30*24*60*60*1000; u.reveal_credits+=5; scheduleSave(); ctx.reply('💎 VIP! 5 ключей добавлено.', {parse_mode:'HTML'}); } else ctx.reply('❌ Не найдено'); });
bot.action('check_premium', async (ctx) => { await ctx.answerCbQuery('Проверка...'); if (await checkYooMoneyPayment(`${ctx.from.id}_premium`)) { const u=db.users[ctx.from.id]; u.is_premium=true; u.premium_expiry=Date.now()+30*24*60*60*1000; scheduleSave(); ctx.reply('👑 PREMIUM! Все маски открыты!', {parse_mode:'HTML'}); } else ctx.reply('❌ Не найдено'); });
bot.action('check_reveal_0', async (ctx) => { await ctx.answerCbQuery('Проверка...'); if (await checkYooMoneyPayment(`${ctx.from.id}_reveal_0`)) { const u=db.users[ctx.from.id]; u.free_keys++; scheduleSave(); ctx.reply('🔑 Ключ куплен! Используй его в сообщениях.', {parse_mode:'HTML'}); } else ctx.reply('❌ Не найдено'); });
bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { const id = ctx.match[1]; await ctx.answerCbQuery('Проверка...'); if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${id}`)){ const u=db.users[ctx.from.id]; u.free_keys++; scheduleSave(); ctx.reply('🔑 Ключ куплен!', {parse_mode:'HTML'}); } else ctx.reply('❌ Не найдено'); });

// === АДМИНКА ===
bot.command('admin', async (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.reply('👑 Админка', { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📊 Стат', 'admin_stats')], [Markup.button.callback('📢 Рассылка', 'admin_broadcast')], [Markup.button.callback('👑 Premium', 'admin_grant_premium')], [Markup.button.callback('🧹 Очистить', 'admin_clear_msgs')]]) }); });
bot.action('admin_stats', async (ctx) => { if (ctx.from.id !== ADMIN_ID) return; await ctx.answerCbQuery(); const u=Object.keys(db.users).length; const m=Object.keys(db.messages).length; const p=Object.values(db.users).filter(u=>u.is_premium&&u.premium_expiry>Date.now()).length; ctx.reply(`📊:\n👥 ${u}\n👑 ${p}\n📬 ${m}`, {parse_mode:'HTML'}); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); adminState.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); adminState.waitingForPremiumId=true; ctx.reply('👑 ID:'); });
bot.action('admin_clear_msgs', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); const c=Object.keys(db.messages).length; db.messages={}; scheduleSave(); ctx.reply(`🧹 ${c}!`); });

bot.launch().then(() => console.log('🤖 Маскарад запущен!')).catch(err => console.error(err));
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
