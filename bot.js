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

// === ШАРДИРОВАННАЯ ФАЙЛОВАЯ БАЗА ДАННЫХ ===
const DIRS = {
    users: path.join(__dirname, 'data', 'users'),
    messages: path.join(__dirname, 'data', 'messages'),
    inboxes: path.join(__dirname, 'data', 'inboxes'),
    payments: path.join(__dirname, 'data', 'payments')
};

// Создаем папки при старте
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

// === ФУНКЦИИ ЛОГИКИ ===
function registerUser(tg_id, username, first_name) {
    const userId = tg_id.toString();
    if (!getUser(userId)) { 
        saveUser({ id: userId, username, first_name, is_premium: false, premium_expiry: 0, ref_count: 0, invited_by: null, keys: 1, is_ghost: false, free_reads_left: 3 }); 
    }
}

function generateId() { return Date.now().toString(36) + Math.random().toString(36).slice(2); }

function addMessage(target_id, text, sender_name, sender_photo, is_open, mood, sender_id) { 
    const id = generateId(); 
    const msg = { id, target_id: target_id.toString(), text, sender_name, sender_photo, is_read: false, is_read_ghost: false, is_revealed: false, is_open, mood, sender_id: sender_id.toString(), reaction: null, created_at: Date.now() };
    saveMessage(msg);
    
    // Добавляем ID сообщения во входящие получателя
    const inbox = getInbox(target_id.toString());
    inbox.push(id);
    saveInbox(target_id.toString(), inbox);
    
    return id; 
}

function getUnreadMessages(target_id) { 
    const inbox = getInbox(target_id.toString());
    const msgs = [];
    inbox.forEach(id => {
        const msg = getMessage(id);
        if (msg && !msg.is_read && !msg.is_read_ghost) msgs.push(msg);
    });
    return msgs.sort((a, b) => b.created_at - a.created_at);
}

function markAsRead(id, isGhost) { 
    const msg = getMessage(id);
    if (!msg) return;
    if (isGhost) msg.is_read_ghost = true; else msg.is_read = true;
    saveMessage(msg);
    
    // Удаляем из инбокса
    if (msg.is_read || msg.is_read_ghost) {
        const inbox = getInbox(msg.target_id);
        const newInbox = inbox.filter(mId => mId !== id);
        saveInbox(msg.target_id, newInbox);
    }
}

function revealMessage(id) { const m = getMessage(id); if(m) { m.is_revealed = true; saveMessage(m); } }
function addKeys(userId, amount) { const u = getUser(userId); if(u) { u.keys += amount; saveUser(u); } }
function spendKeys(userId, amount) { const u = getUser(userId); if(u && u.keys >= amount) { u.keys -= amount; saveUser(u); return true; } return false; }

// === УТИЛИТЫ ===
function getMainMenu() { return Markup.keyboard([['🤫 Шёпоты', '🗝️ Ключи и Ссылка'], ['👑 Премиум', '👤 Профиль']]).resize(); }
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
    } catch (e) { console.error('YooMoney API Error:', e); return false; } 
}

function isUserPremium(user) { if (!user) return false; return user.is_premium && (user.premium_expiry === 0 || user.premium_expiry > Date.now()); }
function getFirstLetter(name) { return name ? name.charAt(0).toUpperCase() + '***' : '🤫'; }
function getFirstAndLastLetter(name) { if (!name || name.length < 2) return '🤫'; return name.charAt(0).toUpperCase() + '***' + name.charAt(name.length - 1).toUpperCase(); }

const MOODS = {
    default: { title: 'Шёпот', text: 'Напиши мне анонимное послание или вопрос' },
    confession: { title: 'Исповедь', text: 'Признайся мне в чём-нибудь анонимно 🤫' },
    truth: { title: 'Только правда', text: 'Задай мне самый откровенный вопрос' },
    crush: { title: 'Симпатия', text: 'Признайся мне в симпатии анонимно ❤️' }
};

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
                    bot.telegram.sendMessage(refId, '👥 По твоей ссылке перешел друг! Твой подарок: 🗝️ +1 Ключ').catch(()=>{});
                }
            }
        }
        return ctx.reply('👋 Добро пожаловать! Тебя пригласили в Шёпот.', { parse_mode: 'HTML', ...getMainMenu() });
    }

    if (payload && payload.startsWith('w_')) {
        const parts = payload.replace('w_', '').split('_mood_');
        const targetId = parts[0]; const mood = parts[1] || 'default';
        const targetUser = getUser(targetId);
        if (!targetUser) return ctx.reply('Этот человек еще не в Шёпоте :(');
        
        bot.telegram.sendMessage(targetId, `👀 <b>Внимание!</b>\nКто-то только что открывал твою ссылку...`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🕵️ Узнать, кто заходил (99 ₽)', `reveal_guest_${userId}`)]]) }).catch(()=>{});

        ctx.session = { targetId, sender_step: 'ask_name', mood };
        return ctx.reply(`🤫 <b>${MOODS[mood].text} для ${targetUser.first_name}</b>\n\n👤 Напиши свое имя:`, { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() });
    }

    ctx.session = {};
    await ctx.reply(`🤫 <b>Добро пожаловать в Шёпот!</b>\n\n📩 Читать тексты — <b>бесплатно</b>.\n🎭 Авторы скрыты... Используй 🗝️ Ключи или Премиум!\n\n🔗 Поделись ссылкой!`, { parse_mode: 'HTML', ...getMainMenu() });
});

bot.hears('🗝️ Ключи и Ссылка', (ctx) => {
    ctx.session = {};
    const user = getUser(ctx.from.id.toString());
    ctx.reply(`🗝️ У тебя: <b>${user.keys} Ключей</b>\n\n1 друг по ссылке = 1 Ключ!\n\n🔗 <b>Выбери ссылку:</b>`, { 
        parse_mode: 'HTML',
        ...Markup.inlineKeyboard([
            [Markup.button.callback('🤫 Обычный Шёпот', 'link_default')],
            [Markup.button.callback('😈 Исповедь', 'link_confession'), Markup.button.callback('🔥 Откровенный вопрос', 'link_truth')],
            [Markup.button.callback('❤️ Симпатия', 'link_crush')],
            [Markup.button.callback('🛒 Купить Ключи', 'shop_keys')]
        ])
    });
});

bot.hears('🤫 Шёпоты', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    registerUser(userId, ctx.from.username, ctx.from.first_name);
    const msgs = getUnreadMessages(userId);
    if (msgs.length === 0) return ctx.reply('📭 Шёпотов пока нет... Поделись ссылкой!');
    ctx.session.msgQueue = msgs.map(m => m.id);
    showNextMessage(ctx);
});

bot.hears('👑 Премиум', (ctx) => {
    ctx.session = {};
    ctx.reply(`👑 <b>Премиум-Шёпот</b>\n\n✅ Все авторы раскрываются бесплатно\n✅ Режим Призрака 👻 навсегда\n✅ Бесконечные чтения`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.callback('👑 3 дня (99 ₽)', 'shop_prem_3')],
            [Markup.button.callback('👑 1 месяц (299 ₽)', 'shop_prem_30')],
            [Markup.button.callback('👑 Навсегда (799 ₽)', 'shop_prem_forever')]
        ])
    });
});

bot.hears('👤 Профиль', (ctx) => {
    ctx.session = {};
    const user = getUser(ctx.from.id.toString());
    if (!user) return;
    const premiumStatus = isUserPremium(user) ? '👑 Активен' : '❌ Нет';
    const ghostStatus = user.is_ghost ? '👻 Да' : '❌ Нет';
    ctx.reply(`👤 <b>Мой профиль</b>\n\n🤫 Имя: <b>${ctx.from.first_name}</b>\n🗝️ Ключи: <b>${user.keys}</b>\n👁 Бесплатных чтений: <b>${user.free_reads_left}</b>\n👻 Призрак: ${ghostStatus}\n👑 Премиум: ${premiumStatus}\n👥 Приглашено: <b>${user.ref_count}</b>`, { parse_mode: 'HTML' });
});

bot.action(/^link_(.+)$/, (ctx) => {
    const mood = ctx.match[1]; const userId = ctx.from.id.toString(); ctx.answerCbQuery();
    ctx.reply(`🔗 <b>Твоя ссылка (${MOODS[mood].title}):</b>\n<code>https://t.me/${ctx.botInfo.username}?start=w_${userId}_mood_${mood}</code>\n\n👥 <b>Реферальная (за друга 🗝️):</b>\n<code>https://t.me/${ctx.botInfo.username}?start=r_${userId}</code>`, { parse_mode: 'HTML' });
});

bot.on('photo', async (ctx) => { if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return; ctx.session.sender_photo = ctx.message.photo[ctx.message.photo.length - 1].file_id; ctx.session.sender_step = 'ask_message'; await ctx.reply('✅ Фото получено! Теперь напиши послание:'); });
bot.on('document', async (ctx) => { if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return; ctx.session.sender_photo = ctx.message.document.thumb ? ctx.message.document.thumb.file_id : ctx.message.document.file_id; ctx.session.sender_step = 'ask_message'; await ctx.reply('✅ Фото получено! Теперь напиши послание:'); });

bot.on('text', async (ctx) => {
    if (!ctx.session) ctx.session = {};
    const text = ctx.message.text; const userId = ctx.from.id.toString();
    
    if (userId === ADMIN_ID) {
        if (ctx.session.waitingForBroadcast) {
            ctx.session.waitingForBroadcast = false; await ctx.reply('📢 Начинаю рассылку...'); let sent = 0; let failed = 0;
            try {
                const userFiles = fs.readdirSync(DIRS.users);
                for (const file of userFiles) { 
                    const uId = file.replace('.json', '');
                    try { await bot.telegram.sendMessage(uId, text, { parse_mode: 'HTML' }); sent++; await new Promise(r => setTimeout(r, 55)); } catch(e) { failed++; } 
                }
            } catch(e) {}
            return ctx.reply(`✅ Отправлено: ${sent}\nНе доставлено: ${failed}`);
        }
        if (ctx.session.waitingForPremiumId) {
            ctx.session.waitingForPremiumId = false; const targetId = text.trim();
            const target = getUser(targetId);
            if (!target) return ctx.reply('❌ Не найден.');
            target.is_premium = true; target.premium_expiry = 0; saveUser(target);
            return ctx.reply(`✅ Premium выдан!`);
        }
    }

    if (ctx.session.sender_step === 'ask_photo') return ctx.reply('📸 Нужно прислать фото.');
    if (ctx.session.sender_step === 'ask_name') { ctx.session.sender_name = text; ctx.session.sender_step = 'ask_photo'; return ctx.reply('📸 Прикрепи свое фото:'); }
    if (ctx.session.sender_step === 'ask_message') {
        if (text.length > 200) return ctx.reply('❌ Максимум 200 символов!');
        ctx.session.sender_text = text; ctx.session.sender_step = 'choose_mode';
        return ctx.reply(`📝 Послание готово: "${text}"\n\nВыбери, как отправить:`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([ [Markup.button.callback('🤫 Анонимно', 'send_anon')], [Markup.button.callback('👤 Открыто', 'send_open')] ]) });
    }
});

bot.action('send_anon', (ctx) => { sendMessage(ctx, false); });
bot.action('send_open', (ctx) => { sendMessage(ctx, true); });

async function sendMessage(ctx, is_open) {
    if (!ctx.session || !ctx.session.targetId) return ctx.answerCbQuery('Ошибка');
    const msgId = addMessage(ctx.session.targetId, ctx.session.sender_text, ctx.session.sender_name, ctx.session.sender_photo, is_open, ctx.session.mood, ctx.from.id.toString());
    const targetId = ctx.session.targetId;
    ctx.session = {};
    await ctx.reply(`✅ Шёпот доставлен!`, getMainMenu());
    const moodEmoji = (ctx.session?.mood === 'crush') ? '❤️' : '🤫';
    try { await bot.telegram.sendMessage(targetId, `${moodEmoji} <b>Тебе пришел новый шёпот!</b>\n\n⏳ <i>Он удалится через 24 часа!</i>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📬 Прочитать', `read_${msgId}`)]]) }); } catch (e) {}
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
        return ctx.reply(`🔒 <b>Бесплатные чтения закончились!</b>\n\nЧтобы прочитать, нужен 1 Ключ или Премиум.\n\n⏳ <i>Сообщение удалится через 24 часа!</i>`, {
            parse_mode: 'HTML',
            ...Markup.inlineKeyboard([ [Markup.button.callback('🗝️ Использовать 1 Ключ', `pay_read_key_${msg.id}`)], [Markup.button.callback('👑 Премиум', 'shop_premium')], [Markup.button.callback('👥 Получить ключ бесплатно', 'link_default')] ])
        });
    }

    if (!isPremium && user.free_reads_left > 0 && !msg.is_open && !hasAccess) {
        user.free_reads_left--; saveUser(user);
    }

    const reactionKeyboard = Markup.inlineKeyboard([[Markup.button.callback('❤️', `react_❤️_${msg.id}`), Markup.button.callback('😂', `react_😂_${msg.id}`), Markup.button.callback('😱', `react_😱_${msg.id}`)], [Markup.button.callback('➡️ Далее', 'skip_msg')]]);

    if (hasAccess) { 
        if (!msg.is_revealed && !msg.is_open) revealMessage(msg.id);
        ctx.answerCbQuery(); 
        ctx.replyWithPhoto(msg.sender_photo, { caption: `📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, parse_mode: 'HTML', ...reactionKeyboard }).catch(() => { ctx.reply(`📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, { parse_mode: 'HTML', ...reactionKeyboard }); });
    } else { 
        ctx.answerCbQuery(); 
        ctx.reply(`📩 <b>Анонимное послание:</b>\n"${msg.text}"\n\n🎭 <i>Автор скрыт. Выбери, как прочитать:</i>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('👁 Бесплатно', `mark_read_${msg.id}`)], [Markup.button.callback('👻 Втайне (49 ₽)', `mark_ghost_${msg.id}`)]]) }); 
    }
}

bot.action(/^mark_read_(.+)$/, async (ctx) => { 
    const msg = getMessage(ctx.match[1]); if (!msg) return ctx.answerCbQuery('Ошибка');
    markAsRead(msg.id, false); ctx.answerCbQuery(); ctx.deleteMessage().catch(()=>{});
    if (msg.is_revealed || msg.is_open) return;
    ctx.reply(`📩 <b>Прочитано!</b>\n"${msg.text}"\n\n🎭 Узнать автора?`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([ [Markup.button.callback(`🗝️ 1 Ключ (${getFirstLetter(msg.sender_name)})`, `hint_1_${msg.id}`)], [Markup.button.callback(`🗝️ 2 Ключа (${getFirstAndLastLetter(msg.sender_name)})`, `hint_2_${msg.id}`)], [Markup.button.callback('💳 Раскрыть (149 ₽)', `buy_reveal_${msg.id}`)], [Markup.button.callback('👑 Премиум', 'shop_premium'), Markup.button.callback('➡️ Далее', 'skip_msg')] ])
    });
});

bot.action(/^mark_ghost_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; const user = getUser(ctx.from.id.toString()); const msg = getMessage(msgId); if (!msg) return ctx.answerCbQuery('Ошибка');
    if (isUserPremium(user) || user.is_ghost) { markAsRead(msgId, true); ctx.answerCbQuery('👻 Втайне!'); ctx.deleteMessage().catch(()=>{}); ctx.reply(`📩 <b>Прочитано втайне:</b>\n"${msg.text}"`, { parse_mode: 'HTML' }); return; }
    ctx.answerCbQuery(); ctx.reply(`👻 <b>Режим Призрака (49 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(49, `${ctx.from.id}_ghost_${msgId}`))], [Markup.button.callback('✅ Я оплатил', `check_ghost_${msgId}`)]]) });
});

bot.action(/^pay_read_key_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; const spent = spendKeys(ctx.from.id.toString(), 1);
    if (spent) { ctx.answerCbQuery('Ключ использован!'); const msg = getMessage(msgId); if(msg) { await showSingleMessage(ctx, msg); } } 
    else { ctx.answerCbQuery('У тебя 0 ключей! Пригласи друга.', true); }
});

bot.action(/^hint_1_(.+)$/, async (ctx) => { const msg = getMessage(ctx.match[1]); const spent = spendKeys(ctx.from.id.toString(), 1); if(spent) await ctx.answerCbQuery(`Подсказка: ${msg.sender_name.charAt(0).toUpperCase()}***`, true); else await ctx.answerCbQuery('Мало ключей!', true); });
bot.action(/^hint_2_(.+)$/, async (ctx) => { const msg = getMessage(ctx.match[1]); const spent = spendKeys(ctx.from.id.toString(), 2); if(spent) await ctx.answerCbQuery(`Подсказка: ${getFirstAndLastLetter(msg.sender_name)}`, true); else await ctx.answerCbQuery('Мало ключей!', true); });

bot.action(/^react_(.+?)_(.+)$/, async (ctx) => {
    const emoji = ctx.match[1]; const msgId = ctx.match[2]; const msg = getMessage(msgId); if (!msg) return ctx.answerCbQuery('Ошибка');
    msg.reaction = emoji; saveMessage(msg); ctx.answerCbQuery('Отправлено!');
    if (msg.sender_id) bot.telegram.sendMessage(msg.sender_id, `💌 Твой шёпот вызвал реакцию: ${emoji}`).catch(()=>{});
    ctx.editMessageReplyMarkup({ inline_keyboard: [[Markup.button.callback('➡️ Далее', 'skip_msg')]] }).catch(()=>{});
});

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });
bot.action(/^reveal_guest_(.+)$/, async (ctx) => { ctx.answerCbQuery(); ctx.reply(`👀 <b>Узнать, кто заходил (99 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_guest_${ctx.match[1]}`))], [Markup.button.callback('✅ Я оплатил', `check_guest_${ctx.match[1]}`)]]) }); });

bot.action('shop_keys', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🗝️ <b>Покупка Ключей</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 3 Ключа (99 ₽)', generatePaymentLink(99, `${ctx.from.id}_keys_3`))], [Markup.button.callback('✅ Я оплатил 3', 'check_keys_3')], [Markup.button.url('💳 10 Ключей (249 ₽)', generatePaymentLink(249, `${ctx.from.id}_keys_10`))], [Markup.button.callback('✅ Я оплатил 10', 'check_keys_10')]]) }); });
bot.action('shop_premium', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('👑 3 дня (99 ₽)', 'shop_prem_3')], [Markup.button.callback('👑 1 мес (299 ₽)', 'shop_prem_30')], [Markup.button.callback('👑 Навсегда (799 ₽)', 'shop_prem_forever')]]) }); });

bot.action('shop_prem_3', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 3 дня (99 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_prem_3`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_3')]]) }); });
bot.action('shop_prem_30', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 1 мес (299 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(299, `${ctx.from.id}_prem_30`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_30')]]) }); });
bot.action('shop_prem_forever', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 Навсегда (799 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_prem_forever`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_forever')]]) }); });
bot.action(/^buy_reveal_(.+)$/, async (ctx) => { ctx.answerCbQuery(); ctx.reply(`🕵️ Раскрыть (149 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${ctx.match[1]}`))], [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${ctx.match[1]}`)]]) }); });

bot.action('check_keys_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_3`)) { addKeys(ctx.from.id, 3); ctx.reply('🗝️ +3 Ключа!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_keys_10', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_10`)) { addKeys(ctx.from.id, 10); ctx.reply('🗝️ +10 Ключей!'); } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.action('check_prem_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_3`)) { const u = getUser(ctx.from.id.toString()); u.is_premium = true; u.premium_expiry = Date.now() + 3*24*60*60*1000; saveUser(u); ctx.reply('👑 Активирован на 3 дня!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_prem_30', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_30`)) { const u = getUser(ctx.from.id.toString()); u.is_premium = true; u.premium_expiry = Date.now() + 30*24*60*60*1000; saveUser(u); ctx.reply('👑 Активирован на месяц!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_prem_forever', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_forever`)) { const u = getUser(ctx.from.id.toString()); u.is_premium = true; u.premium_expiry = 0; saveUser(u); ctx.reply('👑 Активирован навсегда!'); } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.action(/^check_ghost_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_ghost_${ctx.match[1]}`)){ markAsRead(ctx.match[1], true); ctx.reply('👻 Призрак применен!'); const msg = getMessage(ctx.match[1]); if(msg) ctx.reply(`📩 "${msg.text}"`, {parse_mode:'HTML'}); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action(/^check_guest_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_guest_${ctx.match[1]}`)){ const guest = getUser(ctx.match[1]); ctx.reply(`👀 Гость: ${guest ? guest.first_name : 'Аноним'}`, {parse_mode:'HTML'}); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${ctx.match[1]}`)){ const m = getMessage(ctx.match[1]); if(m) { revealMessage(m.id); ctx.replyWithPhoto(m.sender_photo, {caption: `👤 ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}).catch(()=>ctx.reply(`👤 ${m.sender_name}\n\n"${m.text}"`, {parse_mode:'HTML'})); if(m.sender_id) bot.telegram.sendMessage(m.sender_id, `👁 Твой шёпот раскрыли!`).catch(()=>{}); } } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.command('admin', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.session = {}; ctx.reply('👑 Админка', { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📊 Стат', 'admin_stats')], [Markup.button.callback('📢 Рассылка', 'admin_broadcast')], [Markup.button.callback('👑 Premium', 'admin_grant_premium')]]) }); });
bot.action('admin_stats', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; await ctx.answerCbQuery(); const uCount = fs.readdirSync(DIRS.users).length; const mCount = fs.readdirSync(DIRS.messages).length; ctx.reply(`📊:\n👥 ${uCount}\n📬 ${mCount}`); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForPremiumId=true; ctx.reply('👑 ID:'); });

bot.launch().then(() => console.log('🤖 Шёпот (File Shard Scale) запущен!')).catch(err => console.error(err));
