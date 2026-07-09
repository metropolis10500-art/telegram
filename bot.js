require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');
const path = require('path');

const BOT_TOKEN = process.env.BOT_TOKEN;
const YOOMONEY_WALLET = process.env.YOOMONEY_WALLET;
const YOOMONEY_API_TOKEN = process.env.YOOMONEY_API_TOKEN;
const ADMIN_ID = process.env.ADMIN_ID; 

const bot = new Telegraf(BOT_TOKEN);

// === ВСТРОЕННАЯ СЕССИЯ ===
const sessionStore = new Map();
bot.use(async (ctx, next) => {
    const key = ctx.from ? ctx.from.id.toString() : 'default';
    ctx.session = sessionStore.get(key) || {};
    await next();
    sessionStore.set(key, ctx.session);
});

// === ШАРДИРОВАННАЯ БАЗА ДАННЫХ ===
const DIRS = { users: path.join(__dirname, 'data', 'users'), messages: path.join(__dirname, 'data', 'messages'), inboxes: path.join(__dirname, 'data', 'inboxes'), payments: path.join(__dirname, 'data', 'payments') };
Object.values(DIRS).forEach(d => { if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true }); });

function getFilePath(dir, id) { return path.join(DIRS[dir], `${id}.json`); }
function getUser(id) { try { return JSON.parse(fs.readFileSync(getFilePath('users', id), 'utf8')); } catch(e) { return null; } }
function saveUser(user) { fs.writeFileSync(getFilePath('users', user.id), JSON.stringify(user)); }
function getMessage(id) { try { return JSON.parse(fs.readFileSync(getFilePath('messages', id), 'utf8')); } catch(e) { return null; } }
function saveMessage(msg) { fs.writeFileSync(getFilePath('messages', msg.id), JSON.stringify(msg)); }
function getInbox(userId) { try { return JSON.parse(fs.readFileSync(getFilePath('inboxes', userId), 'utf8')); } catch(e) { return []; } }
function saveInbox(userId, inbox) { fs.writeFileSync(getFilePath('inboxes', userId), JSON.stringify(inbox)); }
function isPaymentUsed(label) { return fs.existsSync(getFilePath('payments', label)); }
function markPaymentUsed(label) { fs.writeFileSync(getFilePath('payments', label), JSON.stringify({ date: Date.now() })); }

// === ЛОГИКА ===
function registerUser(tg_id, username, first_name) {
    const userId = tg_id.toString();
    if (!getUser(userId)) { 
        saveUser({ id: userId, username, first_name, is_premium: false, premium_expiry: 0, ref_count: 0, invited_by: null, keys: 1, is_ghost: false, free_reads_left: 3, last_daily: 0, streak: 0 }); 
    }
}

function generateId() { return Date.now().toString(36) + Math.random().toString(36).slice(2); }

function addMessage(target_id, text, sender_name, sender_photo, is_open, mood, sender_id, reply_to) { 
    const id = generateId(); 
    const msg = { id, target_id: target_id.toString(), text, sender_name, sender_photo, is_read: false, is_read_ghost: false, is_revealed: false, is_open, mood, sender_id: sender_id.toString(), reaction: null, reply_to: reply_to || null, created_at: Date.now() };
    saveMessage(msg);
    const inbox = getInbox(target_id.toString());
    inbox.push(id);
    saveInbox(target_id.toString(), inbox);
    return id; 
}

function getUnreadMessages(target_id) { 
    const inbox = getInbox(target_id.toString());
    const msgs = [];
    inbox.forEach(id => { const msg = getMessage(id); if (msg && !msg.is_read && !msg.is_read_ghost) msgs.push(msg); });
    return msgs.sort((a, b) => b.created_at - a.created_at);
}

function markAsRead(id, isGhost) { 
    const msg = getMessage(id); if (!msg) return;
    if (isGhost) msg.is_read_ghost = true; else msg.is_read = true;
    saveMessage(msg);
    if (msg.is_read || msg.is_read_ghost) { const inbox = getInbox(msg.target_id); saveInbox(msg.target_id, inbox.filter(mId => mId !== id)); }
}

function revealMessage(id) { const m = getMessage(id); if(m) { m.is_revealed = true; saveMessage(m); } }
function addKeys(userId, amount) { const u = getUser(userId); if(u) { u.keys += amount; saveUser(u); } }
function spendKeys(userId, amount) { const u = getUser(userId); if(u && u.keys >= amount) { u.keys -= amount; saveUser(u); return true; } return false; }

// ГЛАВНОЕ МЕНЮ С КНОПКОЙ МАГАЗИНА
function getMainMenu() { return Markup.keyboard([['🤫 Шёпоты', '🛒 Магазин'], ['🗓 Бонус', '🔗 Ссылка'], ['👤 Профиль']]).resize(); }
function generatePaymentLink(amount, label) { return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=small&paymentType=AC&sum=${amount}&label=${label}`; }

async function checkYooMoneyPayment(label) { 
    if (isPaymentUsed(label)) return false;
    try { 
        const p = new URLSearchParams(); p.append('label', label); p.append('type', 'in'); 
        const r = await fetch('https://yoomoney.ru/api/operation-history', { method: 'POST', headers: { 'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: p.toString() }); 
        const d = await r.json(); 
        const isSuccess = d.operations && d.operations.some(o => o.status === 'success');
        if (isSuccess) markPaymentUsed(label);
        return isSuccess;
    } catch (e) { return false; } 
}

function isUserPremium(user) { if (!user) return false; return user.is_premium && (user.premium_expiry === 0 || user.premium_expiry > Date.now()); }
function getFirstLetter(name) { return name ? name.charAt(0).toUpperCase() + '***' : '🤫'; }
function getFirstAndLastLetter(name) { if (!name || name.length < 2) return '🤫'; return name.charAt(0).toUpperCase() + '***' + name.charAt(name.length - 1).toUpperCase(); }

// =====================================================================
// === ЛОГИКА БОТА ===
// =====================================================================

bot.start(async (ctx) => {
    const userId = ctx.from.id.toString();
    registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Аноним');
    const payload = ctx.startPayload;

    if (payload && payload.startsWith('r_')) {
        const refId = payload.replace('r_', '');
        if (refId !== userId) {
            const refUser = getUser(refId);
            if (refUser) {
                const me = getUser(userId);
                if (!me.invited_by) {
                    me.invited_by = refId; saveUser(me);
                    refUser.ref_count++; refUser.keys++; saveUser(refUser);
                    bot.telegram.sendMessage(refId, '👥 По твоей ссылке перешел друг! +1 Ключ 🗝').catch(()=>{});
                }
            }
        }
        return ctx.reply('👋 Добро пожаловать! Тебя пригласили в Шёпот.', { parse_mode: 'HTML', ...getMainMenu() });
    }

    if (payload && payload.startsWith('w_')) {
        const parts = payload.replace('w_', '').split('_mood_');
        const targetId = parts[0]; const mood = parts[1] || 'default'; const replyTo = parts[2] || null;
        const targetUser = getUser(targetId);
        if (!targetUser) return ctx.reply('Этот человек еще не в Шёпоте :(');
        
        bot.telegram.sendMessage(targetId, `🚨 <b>Кто-то только что открывал твою ссылку...</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🕵️ Узнать кто (99₽)', `reveal_guest_${userId}`)]]) }).catch(()=>{});

        const textReply = replyTo ? "Напиши ответ на это послание" : "Напиши мне анонимное послание";
        ctx.session = { targetId, sender_step: 'ask_name', mood, replyTo };
        return ctx.reply(`🤫 <b>${textReply} для ${targetUser.first_name}</b>\n\n👤 Укажи свое имя:`, { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() });
    }

    ctx.session = {};
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(`🤫 <b>Добро пожаловать в Шёпот!</b>\n\n📩 Узнай, что скрывают друзья.\n🎭 Авторы скрыты... Но у тебя есть ключи!\n\n🔗 Твоя ссылка:\n<code>${link}</code>`, { parse_mode: 'HTML', ...getMainMenu() });
});

// --- ЕЖЕДНЕВНЫЙ БОНУС ---
bot.hears('🗓 Бонус', (ctx) => {
    const userId = ctx.from.id.toString();
    const user = getUser(userId);
    const now = Date.now();
    const oneDay = 24 * 60 * 60 * 1000;
    
    if (now - user.last_daily < oneDay) {
        const left = Math.ceil((oneDay - (now - user.last_daily)) / (60 * 60 * 1000));
        return ctx.reply(`⏳ Ты уже забирал бонус! Следующий через ${left} ч. Твой стрик: ${user.streak} дней 🔥`);
    }
    
    let streak = user.streak || 0;
    if (now - user.last_daily < 2 * oneDay) streak++; else streak = 1;
    
    let reward = 1;
    let msg = `🗓 <b>Ежедневный бонус!</b>\n\n🗝️ +1 Ключ за визит!\n🔥 Твой стрик: ${streak} дней\n\n`;
    
    if (streak % 7 === 0) { reward = 3; msg += `🎉 СЮРПРИЗ! За 7 дней подряд: +3 Ключа!`; }
    else if (streak % 3 === 0) { reward = 2; msg += `🎁 Бонус за 3 дня подряд: +2 Ключа!`; }
    else { msg += `Приходи завтра, чтобы увеличить стрик!`; }
    
    user.streak = streak; user.keys += reward; user.last_daily = now; saveUser(user);
    ctx.reply(msg, { parse_mode: 'HTML' });
});

// --- КНОПКА ССЫЛКИ ---
bot.hears('🔗 Ссылка', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    const refLink = `https://t.me/${ctx.botInfo.username}?start=r_${userId}`;
    ctx.reply(`🔗 <b>Твоя ссылка для соцсетей:</b>\n<code>${link}</code>\n\n👥 <b>Реферальная (1 друг = 1 Ключ):</b>\n<code>${refLink}</code>`, { 
        parse_mode: 'HTML',
        ...Markup.inlineKeyboard([
            [Markup.button.callback('🤫 Послание', 'link_default'), Markup.button.callback('😈 Исповедь', 'link_confession')],
            [Markup.button.callback('❤️ Симпатия', 'link_crush')]
        ])
    });
});

// ======================================================
// === 🛒 МАГАЗИН (ТАРИФЫ И ЦЕНЫ) ===
// ======================================================
bot.hears('🛒 Магазин', (ctx) => {
    ctx.session = {};
    const user = getUser(ctx.from.id.toString());
    
    ctx.reply(
        `🛒 <b>Магазин Шёпота</b>\n\n` +
        `Здесь ты можешь купить всё для раскрытия тайн!\n\n` +
        `👑 <b>ПРЕМИУМ</b> (Все авторы раскрыты, Призрак, Безлимит чтения)\n` +
        ` ├ 3 дня — <b>99 ₽</b>\n` +
        ` ├ 1 месяц — <b>299 ₽</b>\n` +
        ` └ Навсегда — <b>799 ₽</b>\n\n` +
        `🗝 <b>КЛЮЧИ</b> (Для чтения и подсказок имени. У тебя: ${user.keys})\n` +
        ` ├ 3 Ключа — <b>99 ₽</b>\n` +
        ` └ 10 Ключей — <b>249 ₽</b> (Выгода!)\n\n` +
        `👇 <b>Выбери тариф:</b>`, 
        {
            parse_mode: 'HTML',
            ...Markup.inlineKeyboard([
                // Премиум тарифы
                [Markup.button.callback('👑 Премиум 3 дня (99₽)', 'shop_prem_3')],
                [Markup.button.callback('👑 Премиум 1 месяц (299₽)', 'shop_prem_30')],
                [Markup.button.callback('👑 Премиум НАВСЕГДА (799₽)', 'shop_prem_forever')],
                // Ключи
                [Markup.button.callback('🗝 3 Ключа (99₽)', 'shop_keys_3')],
                [Markup.button.callback('🗝 10 Ключей (249₽)', 'shop_keys_10')]
            ])
        }
    );
});

// Обработка выбора в магазине (Генерация ссылки оплаты)
bot.action('shop_prem_3', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум 3 дня (99 ₽)</b>\n\nНажми "Оплатить", затем после успешной оплаты нажми "Я оплатил":`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_prem_3`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_3')]]) }); });
bot.action('shop_prem_30', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум 1 месяц (299 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(299, `${ctx.from.id}_prem_30`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_30')]]) }); });
bot.action('shop_prem_forever', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум Навсегда (799 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_prem_forever`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_forever')]]) }); });
bot.action('shop_keys_3', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🗝 <b>3 Ключа (99 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_keys_3`))], [Markup.button.callback('✅ Я оплатил', 'check_keys_3')]]) }); });
bot.action('shop_keys_10', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🗝 <b>10 Ключей (249 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(249, `${ctx.from.id}_keys_10`))], [Markup.button.callback('✅ Я оплатил', 'check_keys_10')]]) }); });

bot.hears('🤫 Шёпоты', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    registerUser(userId, ctx.from.username, ctx.from.first_name);
    const msgs = getUnreadMessages(userId);
    if (msgs.length === 0) return ctx.reply('📭 Шёпотов нет... Поделись ссылкой!');
    ctx.session.msgQueue = msgs.map(m => m.id);
    showNextMessage(ctx);
});

bot.hears('👤 Профиль', (ctx) => {
    ctx.session = {};
    const user = getUser(ctx.from.id.toString());
    const premiumStatus = isUserPremium(user) ? '👑 Активен' : '❌ Нет';
    ctx.reply(`👤 <b>Мой профиль</b>\n\n🤫 Имя: <b>${ctx.from.first_name}</b>\n🗝️ Ключи: <b>${user.keys}</b>\n👁 Чтений: <b>${user.free_reads_left}</b>\n🔥 Стрик: <b>${user.streak} дней</b>\n👑 Премиум: ${premiumStatus}\n👥 Рефералов: <b>${user.ref_count}</b>`, { parse_mode: 'HTML' });
});

bot.action(/^link_(.+)$/, (ctx) => {
    const mood = ctx.match[1]; const userId = ctx.from.id.toString(); ctx.answerCbQuery();
    const moods = { default: 'Шёпот', confession: 'Исповедь', crush: 'Симпатия' };
    ctx.reply(`🔗 Ссылка (${moods[mood]}):\n<code>https://t.me/${ctx.botInfo.username}?start=w_${userId}_mood_${mood}</code>`, { parse_mode: 'HTML' });
});

bot.on('photo', async (ctx) => { if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return; ctx.session.sender_photo = ctx.message.photo[ctx.message.photo.length - 1].file_id; ctx.session.sender_step = 'ask_message'; await ctx.reply('✅ Фото получено! Напиши послание:'); });
bot.on('document', async (ctx) => { if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return; ctx.session.sender_photo = ctx.message.document.thumb ? ctx.message.document.thumb.file_id : ctx.message.document.file_id; ctx.session.sender_step = 'ask_message'; await ctx.reply('✅ Фото получено! Напиши послание:'); });

bot.on('text', async (ctx) => {
    if (!ctx.session) ctx.session = {};
    const text = ctx.message.text; const userId = ctx.from.id.toString();
    
    if (userId === ADMIN_ID) {
        if (ctx.session.waitingForBroadcast) { ctx.session.waitingForBroadcast = false; await ctx.reply('📢 Рассылка...'); let s=0,f=0; const uf = fs.readdirSync(DIRS.users); for(const file of uf) { try { await bot.telegram.sendMessage(file.replace('.json',''), text, {parse_mode:'HTML'}); s++; await new Promise(r=>setTimeout(r,55)); } catch(e) { f++; } } return ctx.reply(`✅ ${s}\n❌ ${f}`); }
        if (ctx.session.waitingForPremiumId) { ctx.session.waitingForPremiumId = false; const t = getUser(text.trim()); if(!t) return ctx.reply('❌'); t.is_premium=true; t.premium_expiry=0; saveUser(t); return ctx.reply('✅'); }
    }

    if (ctx.session.sender_step === 'ask_photo') return ctx.reply('📸 Нужно фото.');
    if (ctx.session.sender_step === 'ask_name') { ctx.session.sender_name = text; ctx.session.sender_step = 'ask_photo'; return ctx.reply('📸 Прикрепи фото:'); }
    if (ctx.session.sender_step === 'ask_message') {
        if (text.length > 200) return ctx.reply('❌ Макс 200!');
        ctx.session.sender_text = text; ctx.session.sender_step = 'choose_mode';
        return ctx.reply(`📝 Готово: "${text}"\nОтправить:`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([ [Markup.button.callback('🤫 Анонимно', 'send_anon')], [Markup.button.callback('👤 Открыто', 'send_open')] ]) });
    }
});

bot.action('send_anon', (ctx) => { sendMessage(ctx, false); });
bot.action('send_open', (ctx) => { sendMessage(ctx, true); });

async function sendMessage(ctx, is_open) {
    if (!ctx.session || !ctx.session.targetId) return ctx.answerCbQuery('Ошибка');
    const msgId = addMessage(ctx.session.targetId, ctx.session.sender_text, ctx.session.sender_name, ctx.session.sender_photo, is_open, ctx.session.mood, ctx.from.id.toString(), ctx.session.replyTo);
    const targetId = ctx.session.targetId;
    ctx.session = {};
    await ctx.reply(`✅ Шёпот доставлен!`, getMainMenu());
    try { await bot.telegram.sendMessage(targetId, `🚨 <b>Тебе пришел новый шёпот!</b>\n⏳ <i>Исчезнет через 24 часа...</i>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📬 Прочитать', `read_${msgId}`)]]) }); } catch (e) {}
}

bot.action(/^read_(.+)$/, async (ctx) => { const msg = getMessage(ctx.match[1]); if (!msg) return ctx.answerCbQuery('Устарело'); await showSingleMessage(ctx, msg); });

async function showNextMessage(ctx) { 
    if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Всё прочитано!', { ...getMainMenu() }); 
    const msgId = ctx.session.msgQueue.shift(); const msg = getMessage(msgId); if (!msg) return showNextMessage(ctx);
    await showSingleMessage(ctx, msg);
}

async function showSingleMessage(ctx, msg) {
    const userId = ctx.from.id.toString();
    registerUser(userId, ctx.from.username, ctx.from.first_name);
    const user = getUser(userId);
    const isPremium = isUserPremium(user); const hasAccess = msg.is_open || isPremium || msg.is_revealed;

    if (!isPremium && user.free_reads_left <= 0 && !msg.is_open && !hasAccess) {
        ctx.answerCbQuery();
        return ctx.reply(`🔒 <b>Чтения закончились!</b>\n⏳ Послание скоро удалится!\n\nВыбери, как прочитать:`, {
            parse_mode: 'HTML',
            ...Markup.inlineKeyboard([ 
                [Markup.button.callback('🗝️ Использовать 1 Ключ', `pay_read_key_${msg.id}`)], 
                [Markup.button.url('👥 Бесплатно (Пригласи друга)', `https://t.me/${ctx.botInfo.username}?start=r_${userId}`)], 
                [Markup.button.callback('👑 Купить Премиум (Безлимит)', 'shop_premium_info')] 
            ])
        });
    }

    if (!isPremium && user.free_reads_left > 0 && !msg.is_open && !hasAccess) {
        user.free_reads_left--; saveUser(user);
    }

    const replyMarkup = Markup.inlineKeyboard([
        [Markup.button.callback('❤️', `react_❤️_${msg.id}`), Markup.button.callback('😂', `react_😂_${msg.id}`), Markup.button.callback('😱', `react_😱_${msg.id}`)], 
        [Markup.button.callback('💬 Ответить анонимно', `reply_${msg.id}`)],
        [Markup.button.callback('➡️ Далее', 'skip_msg')]
    ]);

    if (hasAccess) { 
        if (!msg.is_revealed && !msg.is_open) revealMessage(msg.id);
        ctx.answerCbQuery(); 
        ctx.replyWithPhoto(msg.sender_photo, { caption: `📩 "${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, parse_mode: 'HTML', ...replyMarkup }).catch(() => { ctx.reply(`📩 "${msg.text}"\n\n👤 <b>${msg.sender_name}</b>`, { parse_mode: 'HTML', ...replyMarkup }); });
    } else { 
        ctx.answerCbQuery(); 
        ctx.reply(`📩 <b>Анонимное послание:</b>\n"${msg.text}"\n\n🎭 Автор скрыт.`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('👁 Прочитать (бесплатно)', `mark_read_${msg.id}`)], [Markup.button.callback('👻 Втайне / Призрак (49₽)', `mark_ghost_${msg.id}`)]]) }); 
    }
}

// Кнопка ответа на сообщение
bot.action(/^reply_(.+)$/, async (ctx) => {
    const msgId = ctx.match[1]; const msg = getMessage(msgId); if(!msg) return ctx.answerCbQuery('Ошибка');
    const targetId = msg.sender_id; if(!targetId) return ctx.answerCbQuery('Нельзя ответить');
    ctx.session = { targetId: targetId, sender_step: 'ask_name', mood: 'default', replyTo: msgId };
    ctx.answerCbQuery(); ctx.reply(`💬 <b>Ответь анонимно!</b>\n👤 Укажи имя:`, { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() });
});

bot.action('shop_premium_info', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум</b> — все авторы раскрыты автоматически!\n\nЦены:\n3 дня - 99₽\n1 месяц - 299₽\nНавсегда - 799₽`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('👑 Купить Премиум', 'shop_premium')]]) }); });

bot.action('shop_premium', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Выбери тариф Премиума:</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('3 дня (99₽)', 'shop_prem_3')], [Markup.button.callback('1 месяц (299₽)', 'shop_prem_30')], [Markup.button.callback('Навсегда (799₽)', 'shop_prem_forever')]]) }); });

bot.action(/^mark_read_(.+)$/, async (ctx) => { 
    const msg = getMessage(ctx.match[1]); if (!msg) return ctx.answerCbQuery('Ошибка');
    markAsRead(msg.id, false); ctx.answerCbQuery(); ctx.deleteMessage().catch(()=>{});
    if (msg.is_revealed || msg.is_open) return;
    ctx.reply(`📩 Прочитано!\n"${msg.text}"\n\n🎭 Кто автор?`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([ 
            [Markup.button.callback(`🗝️ 1 Ключ (Буква: ${getFirstLetter(msg.sender_name)})`, `hint_1_${msg.id}`)], 
            [Markup.button.callback('💳 Раскрыть полностью (149₽)', `buy_reveal_${msg.id}`)], 
            [Markup.button.url('👥 Нет ключей? Пригласи друга!', `https://t.me/${ctx.botInfo.username}?start=r_${ctx.from.id}`)], 
            [Markup.button.callback('➡️ Далее', 'skip_msg')] 
        ])
    });
});

bot.action(/^mark_ghost_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; const user = getUser(ctx.from.id.toString()); const msg = getMessage(msgId); if (!msg) return ctx.answerCbQuery('Ошибка');
    if (isUserPremium(user) || user.is_ghost) { markAsRead(msgId, true); ctx.answerCbQuery('👻 Втайне!'); ctx.deleteMessage().catch(()=>{}); ctx.reply(`📩 "${msg.text}"`, { parse_mode: 'HTML' }); return; }
    ctx.answerCbQuery(); ctx.reply(`👻 <b>Призрак (49₽)</b> - автор не узнает, что ты читал.`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(49, `${ctx.from.id}_ghost_${msgId}`))], [Markup.button.callback('✅ Я оплатил', `check_ghost_${msgId}`)]]) });
});

bot.action(/^pay_read_key_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; const spent = spendKeys(ctx.from.id.toString(), 1);
    if (spent) { ctx.answerCbQuery('Ключ использован!'); const msg = getMessage(msgId); if(msg) { markAsRead(msgId, false); await showSingleMessage(ctx, msg); } } 
    else { ctx.answerCbQuery('Нет ключей! Зайди в 🛒 Магазин.', true); }
});

bot.action(/^hint_1_(.+)$/, async (ctx) => { const msg = getMessage(ctx.match[1]); const spent = spendKeys(ctx.from.id.toString(), 1); if(spent) await ctx.answerCbQuery(`Имя: ${msg.sender_name.charAt(0).toUpperCase()}***`, true); else await ctx.answerCbQuery('Мало ключей! Зайди в 🛒 Магазин.', true); });

bot.action(/^react_(.+?)_(.+)$/, async (ctx) => {
    const emoji = ctx.match[1]; const msgId = ctx.match[2]; const msg = getMessage(msgId); if (!msg) return ctx.answerCbQuery('Ошибка');
    msg.reaction = emoji; saveMessage(msg); ctx.answerCbQuery('Отправлено!');
    if (msg.sender_id) bot.telegram.sendMessage(msg.sender_id, `💌 Твой шёпот вызвал реакцию: ${emoji}`).catch(()=>{});
    ctx.editMessageReplyMarkup({ inline_keyboard: [[Markup.button.callback('💬 Ответить', `reply_${msg.id}`)], [Markup.button.callback('➡️ Далее', 'skip_msg')]] }).catch(()=>{});
});

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });
bot.action(/^reveal_guest_(.+)$/, async (ctx) => { ctx.answerCbQuery(); ctx.reply(`👀 <b>Узнать гостя (99₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_guest_${ctx.match[1]}`))], [Markup.button.callback('✅ Я оплатил', `check_guest_${ctx.match[1]}`)]]) }); });

bot.action(/^buy_reveal_(.+)$/, async (ctx) => { ctx.answerCbQuery(); ctx.reply(`🕵️ <b>Раскрыть автора полностью (149₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${ctx.match[1]}`))], [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${ctx.match[1]}`)]]) }); });

// === ПРОВЕРКИ ОПЛАТ ===
bot.action('check_keys_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_3`)) { addKeys(ctx.from.id, 3); ctx.reply('🗝️ +3 Ключа!'); } else { ctx.reply('❌ Не найдено.'); } });
bot.action('check_keys_10', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_10`)) { addKeys(ctx.from.id, 10); ctx.reply('🗝️ +10 Ключей!'); } else { ctx.reply('❌ Не найдено.'); } });
bot.action('check_prem_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_3`)) { const u = getUser(ctx.from.id.toString()); u.is_premium = true; u.premium_expiry = Date.now() + 3*24*60*60*1000; saveUser(u); ctx.reply('👑 Активирован на 3 дня!'); } else { ctx.reply('❌ Не найдено.'); } });
bot.action('check_prem_30', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_30`)) { const u = getUser(ctx.from.id.toString()); u.is_premium = true; u.premium_expiry = Date.now() + 30*24*60*60*1000; saveUser(u); ctx.reply('👑 Активирован на 1 месяц!'); } else { ctx.reply('❌ Не найдено.'); } });
bot.action('check_prem_forever', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_forever`)) { const u = getUser(ctx.from.id.toString()); u.is_premium = true; u.premium_expiry = 0; saveUser(u); ctx.reply('👑 Премиум Навсегда активирован!'); } else { ctx.reply('❌ Не найдено.'); } });
bot.action(/^check_ghost_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_ghost_${ctx.match[1]}`)){ markAsRead(ctx.match[1], true); ctx.reply('👻 Призрак применен!'); const msg = getMessage(ctx.match[1]); if(msg) ctx.reply(`📩 "${msg.text}"`, {parse_mode:'HTML'}); } else { ctx.reply('❌'); } });
bot.action(/^check_guest_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_guest_${ctx.match[1]}`)){ const guest = getUser(ctx.match[1]); ctx.reply(`👀 Гость: ${guest ? guest.first_name : 'Аноним'}`, {parse_mode:'HTML'}); } else { ctx.reply('❌'); } });
bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${ctx.match[1]}`)){ const m = getMessage(ctx.match[1]); if(m) { revealMessage(m.id); ctx.replyWithPhoto(m.sender_photo, {caption: `👤 ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}).catch(()=>ctx.reply(`👤 ${m.sender_name}\n\n"${m.text}"`, {parse_mode:'HTML'})); if(m.sender_id) bot.telegram.sendMessage(m.sender_id, `👁 Твой шёпот раскрыли!`).catch(()=>{}); } } else { ctx.reply('❌'); } });

bot.command('admin', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.session = {}; ctx.reply('👑 Админка', { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📊 Стат', 'admin_stats')], [Markup.button.callback('📢 Рассылка', 'admin_broadcast')], [Markup.button.callback('👑 Premium', 'admin_grant_premium')]]) }); });
bot.action('admin_stats', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; await ctx.answerCbQuery(); const uCount = fs.readdirSync(DIRS.users).length; ctx.reply(`📊 Юзеров: ${uCount}`); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForPremiumId=true; ctx.reply('👑 ID:'); });

bot.launch().then(() => console.log('🤖 Шёпот (10k/day Scale) запущен!')).catch(err => console.error(err));
