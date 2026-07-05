const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

// === НАСТРОЙКИ ===
const BOT_TOKEN = '8878972156:AAHIvVDWZvZxGDYE0CqUeOdHTGXoTKOYiSI';
const YOOMONEY_WALLET = '4100118935779591';
const YOOMONEY_API_TOKEN = '5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191';
const DB_FILE = './database.json';
const ADMIN_ID = 5494544187; // ВСТАВЬ СЮДА СВОЙ TELEGRAM ID (числом, без кавычек!)

const bot = new Telegraf(BOT_TOKEN);

// === ОПТИМИЗИРОВАННАЯ БАЗА ДАННЫХ ===
let db = { users: {}, messages: {} };
if (fs.existsSync(DB_FILE)) {
    try {
        const loadedData = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        db.users = loadedData.users || {};
        if (Array.isArray(loadedData.messages)) { loadedData.messages.forEach(m => db.messages[m.id] = m); } 
        else { db.messages = loadedData.messages || {}; }
    } catch (e) { console.error('Ошибка загрузки БД:', e); }
}

let saveTimeout = null;
function scheduleSave() {
    if (!saveTimeout) {
        saveTimeout = setTimeout(() => { fs.writeFile(DB_FILE, JSON.stringify(db, null, 2), (err) => { if (err) console.error(err); }); saveTimeout = null; }, 2000);
    }
}

// Автоочистка
setInterval(() => {
    const threeDaysAgo = Date.now() - 3 * 24 * 60 * 60 * 1000;
    let deletedCount = 0;
    Object.keys(db.messages).forEach(id => { if (db.messages[id].is_unlocked && db.messages[id].id < threeDaysAgo) { delete db.messages[id]; deletedCount++; } });
    if (deletedCount > 0) { console.log(`🧹 Удалено ${deletedCount} старых сообщений`); scheduleSave(); }
}, 3600000);

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    if (!db.users[tg_id]) { db.users[tg_id] = { username, first_name, is_premium: false, premium_expiry: 0, dating_active: false, age: 0, city: "", bio: "", liked_by: [], seen_profiles: [] }; scheduleSave(); }
}
function addMessage(target_id, text, sender_hint, aura = "🌙 Нейтральная", type = "whisper") { const id = Date.now(); db.messages[id] = { id, target_id, text, sender_hint, aura, type, is_unlocked: false }; scheduleSave(); return id; }
function getUnreadMessages(target_id) { return Object.values(db.messages).filter(m => m.target_id === target_id && !m.is_unlocked); }
function getMessageById(id) { return db.messages[id]; }
function unlockMessage(id) { const m = db.messages[id]; if (m) { m.is_unlocked = true; scheduleSave(); } }

// === УТИЛИТЫ ===
function detectAura(text) { const t = text.toLowerCase(); if (t.match(/люблю|нрав|красив|горяч/)) return "🔥 Пылкая"; if (t.match(/ненави|дурак|туп/)) return "⚡️ Грозовая"; return "🌙 Лунная"; }
function getMainMenu() { return Markup.keyboard([['🔥 Тайные Симпатии', '🔒 Мои послания'], ['🔗 Моя ссылка', '💰 Магазин']]).resize(); }
function generatePaymentLink(amount, label) { return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=small&paymentType=AC&sum=${amount}&label=${label}`; }
async function checkYooMoneyPayment(label) { try { const p = new URLSearchParams(); p.append('label', label); p.append('type', 'in'); const r = await fetch('https://yoomoney.ru/api/operation-history', { method: 'POST', headers: { 'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: p.toString() }); const d = await r.json(); return d.operations && d.operations.some(o => o.status === 'success'); } catch (e) { return false; } }

// Состояние админа (для рассылок/выдач)
let adminState = {};

// =====================================================================
// === ЛОГИКА БОТА (ПОЛЬЗОВАТЕЛИ) ===
// =====================================================================

bot.start(async (ctx) => {
  const userId = ctx.from.id;
  registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Аноним');
  const payload = ctx.startPayload;
  if (payload && payload.startsWith('w_')) {
    const targetId = parseInt(payload.replace('w_', ''));
    const targetUser = db.users[targetId];
    if (!targetUser) return ctx.reply('Пользователь не найден :(');
    ctx.session = { targetId: targetId };
    await ctx.reply(`🤫 <b>Напиши послание для ${targetUser.first_name}</b>`, { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() });
  } else {
    ctx.session = {};
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(`👋 <b>Добро пожаловать в Шёпот!</b>\n\n🔗 <code>${link}</code>`, { parse_mode: 'HTML', ...getMainMenu() });
  }
});

bot.hears('🔥 Тайные Симпатии', async (ctx) => { const user = db.users[ctx.from.id]; if (!user.dating_active) return ctx.reply(`🔥 Создай анкету!`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('✍️ Создать', 'dating_start')]]) }); showNextProfile(ctx); });
bot.hears('🔒 Мои послания', (ctx) => { const msgs = getUnreadMessages(ctx.from.id); if (msgs.length === 0) return ctx.reply('📭 Нет посланий.'); ctx.session = ctx.session || {}; ctx.session.msgQueue = msgs.map(m => m.id); showNextLockedMessage(ctx); });
bot.hears('🔗 Моя ссылка', (ctx) => { ctx.reply(`🔗 <code>https://t.me/${ctx.botInfo.username}?start=w_${ctx.from.id}</code>`, { parse_mode: 'HTML' }); });
bot.hears('💰 Магазин', (ctx) => { ctx.reply(`🔑 <b>Магазин Ключей</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🔓 Открыть 1 (99₽)', 'shop_unlock1')], [Markup.button.callback('🗝 Открыть 5 (399₽)', 'shop_unlock5')], [Markup.button.callback('👑 PREMIUM навсегда (799₽)', 'shop_premium')]]) }); });

bot.action('dating_start', (ctx) => { ctx.answerCbQuery(); ctx.session = { dating_step: 'age' }; ctx.reply('📅 Возраст? (цифра)', { reply_markup: Markup.removeKeyboard() }); });
bot.action('skip_profile', (ctx) => { ctx.answerCbQuery(); showNextProfile(ctx); });
bot.action('like_profile', (ctx) => { const tid = ctx.session.currentProfileId; if(!tid) return; const t = db.users[tid]; if (!t.liked_by.includes(ctx.from.id)) { t.liked_by.push(ctx.from.id); scheduleSave(); } const me = db.users[ctx.from.id]; if (me.liked_by.includes(tid)) { ctx.answerCbQuery('Взаимно! ❤️', true); const h1 = `Имя на: <b>${me.first_name.charAt(0)}...</b>`; const m1 = addMessage(tid, `Вы понравились ${me.first_name}!`, h1, "🔥 Пылкая", "like"); bot.telegram.sendMessage(tid, `❤️ Взаимность!\n📊 Аура: 🔥 Пылкая\n\n🔑 Заперто!`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🔓 Открыть', `read_${m1}`)]]) }); const h2 = `Имя на: <b>${t.first_name.charAt(0)}...</b>`; const m2 = addMessage(ctx.from.id, `Вы понравились ${t.first_name}!`, h2, "🔥 Пылкая", "like"); ctx.reply(`❤️ Взаимность!\n📊 Аура: 🔥 Пылкая\n\n🔑 Заперто!`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🔓 Открыть', `read_${m2}`)]]) }); } else { ctx.answerCbQuery('Лайк!'); showNextProfile(ctx); } });

function showNextProfile(ctx) { const me = db.users[ctx.from.id]; const c = Object.values(db.users).filter(u => u.dating_active && u.tg_id !== ctx.from.id && !me.seen_profiles.includes(u.tg_id)); if (c.length === 0) return ctx.reply('😔 Анкет нет.', { reply_markup: getMainMenu() }); const r = c[Math.floor(Math.random() * c.length)]; me.seen_profiles.push(r.tg_id); scheduleSave(); ctx.session.currentProfileId = r.tg_id; ctx.reply(`👤 <b>${r.first_name}, ${r.age}</b>\n🏙 ${r.city}\n\n📝 ${r.bio}`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('❤️', 'like_profile'), Markup.button.callback('👎', 'skip_profile')]]) }); }

bot.on('text', async (ctx) => {
  if (!ctx.session) ctx.session = {};
  const text = ctx.message.text;

  // === ЛОГИКА АДМИНА (Рассылка / Выдача Premium) ===
  if (ctx.from.id === ADMIN_ID) {
      if (adminState.waitingForBroadcast) {
          adminState.waitingForBroadcast = false;
          const users = Object.keys(db.users);
          let sent = 0;
          for (const id of users) { try { await bot.telegram.sendMessage(id, text, { parse_mode: 'HTML' }); sent++; await new Promise(r => setTimeout(r, 50)); } catch(e) {} }
          return ctx.reply(`✅ Рассылка завершена! Отправлено: ${sent}/${users.length}`);
      }
      if (adminState.waitingForPremiumId) {
          adminState.waitingForPremiumId = false;
          const targetId = parseInt(text);
          if (!db.users[targetId]) return ctx.reply('❌ Пользователь не найден в базе.');
          db.users[targetId].is_premium = true; db.users[targetId].premium_expiry = Date.now() + 30*24*60*60*1000;
          scheduleSave();
          return ctx.reply(`✅ Premium выдан пользователю ${db.users[targetId].first_name} (${targetId})`);
      }
  }

  // Анкета
  if (ctx.session.dating_step === 'age') { const a = parseInt(text); if (isNaN(a)) return ctx.reply('Цифрой!'); db.users[ctx.from.id].age = a; scheduleSave(); ctx.session.dating_step = 'city'; return ctx.reply('🏙 Город?'); }
  if (ctx.session.dating_step === 'city') { db.users[ctx.from.id].city = text; scheduleSave(); ctx.session.dating_step = 'bio'; return ctx.reply('📝 О себе:'); }
  if (ctx.session.dating_step === 'bio') { const u=db.users[ctx.from.id]; u.bio=text; u.dating_active=true; scheduleSave(); ctx.session.dating_step=null; return ctx.reply('✅ Готово!', { reply_markup: getMainMenu() }); }

  // Послания
  if (ctx.session.targetId) {
    const tid = ctx.session.targetId; if (text.length > 200) return ctx.reply('Макс 200!');
    const hint = `Имя на: <b>${ctx.from.first_name.charAt(0)}...</b>`; const aura = detectAura(text);
    const mId = addMessage(tid, text, hint, aura, "whisper");
    ctx.session = {};
    await ctx.reply('✅ Заперто и отправлено!', { parse_mode: 'HTML', ...getMainMenu() });
    try { await bot.telegram.sendMessage(tid, `🤫 Новая тайна!\n📊 Аура: <b>${aura}</b>\n\n🔑 Заперто!`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🔓 Открыть', `read_${mId}`)]]) }); } catch (e) {}
  }
});

// === ЧТЕНИЕ ЗАБЛОКИРОВАННЫХ ===
bot.action(/^read_(.+)$/, (ctx) => { const mId=ctx.match[1]; const m=getMessageById(parseInt(mId)); if(!m) return ctx.answerCbQuery('Ошибка'); const u=db.users[ctx.from.id]; const isP = u.is_premium && u.premium_expiry > Date.now(); if (m.is_unlocked || isP) { m.is_unlocked=true; scheduleSave(); ctx.answerCbQuery(); ctx.reply(`🔓 Открыто!\n"${m.text}"\n\n🕵️ ${m.sender_hint.replace('...', ctx.from.first_name)}`, {parse_mode:'HTML'}); } else { ctx.answerCbQuery(); ctx.reply(`🔒 Заперто! Аура: ${m.aura}\nКупи ключ!`, {parse_mode:'HTML', ...Markup.inlineKeyboard([[Markup.button.url('🔓 Ключ (99₽)', generatePaymentLink(99, `${ctx.from.id}_direct_${mId}`))], [Markup.button.callback('✅ Оплатил', `check_direct_${mId}`)]]) }); }});

function showNextLockedMessage(ctx) { if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Конец.', { reply_markup: getMainMenu() }); const mId=ctx.session.msgQueue.shift(); const m=getMessageById(mId); if(!m) return showNextLockedMessage(ctx); const u=db.users[ctx.from.id]; const isP=u.is_premium && u.premium_expiry>Date.now(); if(m.is_unlocked || isP){m.is_unlocked=true;scheduleSave();ctx.reply(`🔓 "${m.text}"\n🕵️ ${m.sender_hint.replace('...', ctx.from.first_name)}`, {parse_mode:'HTML'}); return showNextLockedMessage(ctx);} else {ctx.reply(`🔒 Аура: ${m.aura}. Купи ключ!`, {parse_mode:'HTML', ...Markup.inlineKeyboard([[Markup.button.url('🔓 Ключ (99₽)', generatePaymentLink(99, `${ctx.from.id}_direct_${m.id}`))], [Markup.button.callback('✅ Оплатил', `check_direct_${m.id}`)], [Markup.button.callback('➡️ Пропустить', 'skip_msg')]]) });}}
bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextLockedMessage(ctx); });

// === ОПЛАТЫ ===
bot.action('shop_unlock1', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🔓 1 послание (99₽)`, {parse_mode:'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_unlock1`))], [Markup.button.callback('✅ Я оплатил', 'check_unlock1')]]) }); });
bot.action('shop_unlock5', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🗝 5 посланий (399₽)`, {parse_mode:'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(399, `${ctx.from.id}_unlock5`))], [Markup.button.callback('✅ Я оплатил', 'check_unlock5')]]) }); });
bot.action('shop_premium', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 PREMIUM (799₽)`, {parse_mode:'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_premium`))], [Markup.button.callback('✅ Я оплатил', 'check_premium')]]) }); });

bot.action('check_premium', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_premium`)) { const u=db.users[ctx.from.id]; u.is_premium=true; u.premium_expiry=Date.now()+30*24*60*60*1000; scheduleSave(); ctx.reply('👑 PREMIUM активирован!', {parse_mode:'HTML'}); } else ctx.reply('❌ Не найдено'); });
bot.action('check_unlock1', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_unlock1`)) { const m = getUnreadMessages(ctx.from.id)[0]; if(m){unlockMessage(m.id); ctx.reply(`🔓 "${m.text}"\n🕵️ ${m.sender_hint.replace('...', ctx.from.first_name)}`, {parse_mode:'HTML'});} } else ctx.reply('❌ Не найдено'); });
bot.action('check_unlock5', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_unlock5`)) { const m = getUnreadMessages(ctx.from.id).slice(0, 5); m.forEach(msg=>unlockMessage(msg.id)); ctx.reply(`🗝 Открыто ${m.length}!`, {parse_mode:'HTML'}); } else ctx.reply('❌ Не найдено'); });
bot.action(/^check_direct_(.+)$/, async (ctx) => { const id=ctx.match[1]; await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_direct_${id}`)){ const m=getMessageById(parseInt(id)); if(m){unlockMessage(m.id); ctx.reply(`🔓 "${m.text}"\n🕵️ ${m.sender_hint.replace('...', ctx.from.first_name)}`, {parse_mode:'HTML'});} } else ctx.reply('❌ Не найдено'); });

// =====================================================================
// === АДМИН-ПАНЕЛЬ ===
// =====================================================================

bot.command('admin', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    ctx.reply('👑 <b>Админ-панель</b>\nВыберите действие:', {
        parse_mode: 'HTML',
        ...Markup.inlineKeyboard([
            [Markup.button.callback('📊 Статистика', 'admin_stats')],
            [Markup.button.callback('📢 Сделать рассылку', 'admin_broadcast')],
            [Markup.button.callback('👑 Выдать Premium', 'admin_grant_premium')],
            [Markup.button.callback('🧹 Очистить базу сообщений', 'admin_clear_msgs')]
        ])
    });
});

bot.action('admin_stats', async (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    await ctx.answerCbQuery();
    const totalUsers = Object.keys(db.users).length;
    const totalMsgs = Object.keys(db.messages).length;
    const lockedMsgs = Object.values(db.messages).filter(m => !m.is_unlocked).length;
    const premiumUsers = Object.values(db.users).filter(u => u.is_premium && u.premium_expiry > Date.now()).length;
    
    ctx.reply(`📊 <b>Статистика бота:</b>\n\n👥 Всего пользователей: <b>${totalUsers}</b>\n👑 Premium пользователей: <b>${premiumUsers}</b>\n\n📬 Всего сообщений в базе: <b>${totalMsgs}</b>\n🔒 Заблокировано (не оплачено): <b>${lockedMsgs}</b>`, { parse_mode: 'HTML' });
});

bot.action('admin_broadcast', (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    ctx.answerCbQuery();
    adminState.waitingForBroadcast = true;
    ctx.reply('📢 <b>Рассылка</b>\n\nОтправьте текст, который получат ВСЕ пользователи бота (поддерживается HTML):', { parse_mode: 'HTML' });
});

bot.action('admin_grant_premium', (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    ctx.answerCbQuery();
    adminState.waitingForPremiumId = true;
    ctx.reply('👑 <b>Выдача Premium</b>\n\nОтправьте Telegram ID пользователя (числом):', { parse_mode: 'HTML' });
});

bot.action('admin_clear_msgs', (ctx) => {
    if (ctx.from.id !== ADMIN_ID) return;
    ctx.answerCbQuery();
    const count = Object.keys(db.messages).length;
    db.messages = {}; // Полная очистка сообщений
    scheduleSave();
    ctx.reply(`🧹 База сообщений очищена!\nУдалено ${count} записей. Пользователи не затронуты.`);
});

// === ЗАПУСК ===
bot.launch().then(() => console.log('🤖 Бот "Шёпот" (Pay-to-Read + Admin) запущен!')).catch(err => console.error(err));
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
