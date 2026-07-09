require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const sqlite = require('sqlite');
const fs = require('fs');

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

// === ПОДКЛЮЧЕНИЕ К SQLITE ===
let db;
async function connectDB() {
    db = await sqlite.open('./database.sqlite');
    
    // Создаем таблицы, если их нет (с нужными индексами для скорости)
    await db.run(`CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, username TEXT, first_name TEXT, 
        is_premium INTEGER DEFAULT 0, premium_expiry INTEGER DEFAULT 0, 
        ref_count INTEGER DEFAULT 0, invited_by TEXT, 
        keys INTEGER DEFAULT 1, is_ghost INTEGER DEFAULT 0, free_reads_left INTEGER DEFAULT 3
    )`);
    
    await db.run(`CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, target_id TEXT, text TEXT, sender_name TEXT, sender_photo TEXT, 
        is_read INTEGER DEFAULT 0, is_read_ghost INTEGER DEFAULT 0, is_revealed INTEGER DEFAULT 0, 
        is_open INTEGER DEFAULT 0, mood TEXT DEFAULT 'default', sender_id TEXT, 
        reaction TEXT, created_at INTEGER
    )`);
    
    await db.run(`CREATE TABLE IF NOT EXISTS payments (
        label TEXT PRIMARY KEY, created_at INTEGER
    )`);
    
    // Индексы для моментального поиска (критично для 100к+)
    await db.run(`CREATE INDEX IF NOT EXISTS idx_target_read ON messages (target_id, is_read, is_read_ghost)`);
    
    console.log('✅ Подключено к SQLite!');
}

// === ФУНКЦИИ БАЗЫ ДАННЫХ ===
async function registerUser(tg_id, username, first_name) {
    const userId = tg_id.toString();
    const existing = await db.get('SELECT id FROM users WHERE id = ?', [userId]);
    if (!existing) { 
        await db.run(`INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)`, [userId, username, first_name]); 
    }
}

function generateId() { return Date.now().toString(36) + Math.random().toString(36).slice(2); }

async function addMessage(target_id, text, sender_name, sender_photo, is_open, mood, sender_id) { 
    const id = generateId(); 
    await db.run(`INSERT INTO messages (id, target_id, text, sender_name, sender_photo, is_open, mood, sender_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, 
        [id, target_id.toString(), text, sender_name, sender_photo, is_open ? 1 : 0, mood, sender_id.toString(), Date.now()]); 
    return id; 
}

async function getUnreadMessages(target_id) { 
    return await db.all(`SELECT * FROM messages WHERE target_id = ? AND is_read = 0 AND is_read_ghost = 0 ORDER BY created_at DESC`, [target_id.toString()]);
}

async function getMessageById(id) { return await db.get('SELECT * FROM messages WHERE id = ?', [id]); }

async function markAsRead(id, isGhost) { 
    if (isGhost) await db.run('UPDATE messages SET is_read_ghost = 1 WHERE id = ?', [id]);
    else await db.run('UPDATE messages SET is_read = 1 WHERE id = ?', [id]);
}

async function revealMessage(id) { await db.run('UPDATE messages SET is_revealed = 1 WHERE id = ?', [id]); }

async function addKeys(userId, amount) { await db.run('UPDATE users SET keys = keys + ? WHERE id = ?', [amount, userId.toString()]); }

async function spendKeys(userId, amount) { 
    const user = await db.get('SELECT keys FROM users WHERE id = ?', [userId.toString()]);
    if (user && user.keys >= amount) {
        await db.run('UPDATE users SET keys = keys - ? WHERE id = ?', [amount, userId.toString()]);
        return true;
    }
    return false;
}

// === УТИЛИТЫ ===
function getMainMenu() { 
    return Markup.keyboard([
        ['🤫 Шёпоты', '🗝️ Ключи и Ссылка'], 
        ['👑 Премиум', '👤 Профиль']
    ]).resize(); 
}

function generatePaymentLink(amount, label) { 
    return `https://yoomoney.ru/quickpay/confirm.xml?receiver=${YOOMONEY_WALLET}&quickpay-form=small&paymentType=AC&sum=${amount}&label=${label}`; 
}

async function checkYooMoneyPayment(label) { 
    const used = await db.get('SELECT label FROM payments WHERE label = ?', [label]);
    if (used) return false;

    try { 
        const p = new URLSearchParams(); p.append('label', label); p.append('type', 'in'); 
        const r = await fetch('https://yoomoney.ru/api/operation-history', { method: 'POST', headers: { 'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: p.toString() }); 
        const d = await r.json(); 
        const isSuccess = d.operations && d.operations.some(o => o.status === 'success');
        if (isSuccess) { 
            await db.run('INSERT INTO payments (label, created_at) VALUES (?, ?)', [label, Date.now()]); 
        }
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
    await registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Аноним');
    const payload = ctx.startPayload;

    if (payload && payload.startsWith('r_')) {
        const refId = payload.replace('r_', '');
        if (refId !== userId) {
            const refUser = await db.get('SELECT id FROM users WHERE id = ?', [refId]);
            if (refUser) {
                const me = await db.get('SELECT invited_by FROM users WHERE id = ?', [userId]);
                if (!me.invited_by) {
                    await db.run('UPDATE users SET invited_by = ? WHERE id = ?', [refId, userId]);
                    await db.run('UPDATE users SET ref_count = ref_count + 1, keys = keys + 1 WHERE id = ?', [refId]);
                    bot.telegram.sendMessage(refId, '👥 По твоей ссылке перешел друг! Твой подарок: 🗝️ +1 Ключ').catch(()=>{});
                }
            }
        }
        return ctx.reply('👋 Добро пожаловать! Тебя пригласили в Шёпот.', { parse_mode: 'HTML', ...getMainMenu() });
    }

    if (payload && payload.startsWith('w_')) {
        const parts = payload.replace('w_', '').split('_mood_');
        const targetId = parts[0];
        const mood = parts[1] || 'default';
        
        const targetUser = await db.get('SELECT first_name FROM users WHERE id = ?', [targetId]);
        if (!targetUser) return ctx.reply('Этот человек еще не в Шёпоте :(');
        
        bot.telegram.sendMessage(targetId, 
            `👀 <b>Внимание!</b>\nКто-то только что открывал твою ссылку, чтобы написать шёпот...`, 
            { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('🕵️ Узнать, кто заходил (99 ₽)', `reveal_guest_${userId}`)]]) }
        ).catch(()=>{});

        ctx.session = { targetId, sender_step: 'ask_name', mood };
        return ctx.reply(`🤫 <b>${MOODS[mood].text} для ${targetUser.first_name}</b>\n\n👤 Напиши свое имя:`, { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() });
    }

    ctx.session = {};
    await ctx.reply(`🤫 <b>Добро пожаловать в Шёпот!</b>\n\n📩 Читать тексты — <b>бесплатно</b>.\n🎭 Авторы скрыты... Используй 🗝️ Ключи или Премиум!\n\n🔗 Поделись ссылкой!`, { parse_mode: 'HTML', ...getMainMenu() });
});

// --- КНОПКИ МЕНЮ ---
bot.hears('🗝️ Ключи и Ссылка', async (ctx) => {
    ctx.session = {};
    const user = await db.get('SELECT keys FROM users WHERE id = ?', [ctx.from.id.toString()]);
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

bot.hears('🤫 Шёпоты', async (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    await registerUser(userId, ctx.from.username, ctx.from.first_name);
    const msgs = await getUnreadMessages(userId);
    if (msgs.length === 0) return ctx.reply('📭 Шёпотов пока нет... Поделись ссылкой!');
    ctx.session.msgQueue = msgs.map(m => m.id);
    showNextMessage(ctx);
});

bot.hears('👑 Премиум', (ctx) => {
    ctx.session = {};
    ctx.reply(`👑 <b>Премиум-Шёпот</b>\n\n✅ Все авторы раскрываются бесплатно\n✅ Режим Призрака 👻 навсегда\n✅ Бесконечные чтения\n\nВыбери тариф:`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.callback('👑 3 дня (99 ₽)', 'shop_prem_3')],
            [Markup.button.callback('👑 1 месяц (299 ₽)', 'shop_prem_30')],
            [Markup.button.callback('👑 Навсегда (799 ₽)', 'shop_prem_forever')]
        ])
    });
});

bot.hears('👤 Профиль', async (ctx) => {
    ctx.session = {};
    const user = await db.get('SELECT * FROM users WHERE id = ?', [ctx.from.id.toString()]);
    if (!user) return;
    const premiumStatus = isUserPremium(user) ? '👑 Активен' : '❌ Нет';
    const ghostStatus = user.is_ghost ? '👻 Да' : '❌ Нет';
    ctx.reply(`👤 <b>Мой профиль</b>\n\n🤫 Имя: <b>${ctx.from.first_name}</b>\n🗝️ Ключи: <b>${user.keys}</b>\n👁 Бесплатных чтений: <b>${user.free_reads_left}</b>\n👻 Призрак: ${ghostStatus}\n👑 Премиум: ${premiumStatus}\n👥 Приглашено: <b>${user.ref_count}</b>`, { parse_mode: 'HTML' });
});

bot.action(/^link_(.+)$/, (ctx) => {
    const mood = ctx.match[1];
    const userId = ctx.from.id.toString();
    ctx.answerCbQuery();
    ctx.reply(`🔗 <b>Твоя ссылка (${MOODS[mood].title}):</b>\n<code>https://t.me/${ctx.botInfo.username}?start=w_${userId}_mood_${mood}</code>\n\n👥 <b>Реферальная (за друга 🗝️):</b>\n<code>https://t.me/${ctx.botInfo.username}?start=r_${userId}</code>`, { parse_mode: 'HTML' });
});

// --- ОБРАБОТКА ФОТО И ДОКУМЕНТОВ ---
bot.on('photo', async (ctx) => { if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return; ctx.session.sender_photo = ctx.message.photo[ctx.message.photo.length - 1].file_id; ctx.session.sender_step = 'ask_message'; await ctx.reply('✅ Фото получено! Теперь напиши послание:'); });
bot.on('document', async (ctx) => { if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return; ctx.session.sender_photo = ctx.message.document.thumb ? ctx.message.document.thumb.file_id : ctx.message.document.file_id; ctx.session.sender_step = 'ask_message'; await ctx.reply('✅ Фото получено! Теперь напиши послание:'); });

// --- ОБРАБОТКА ТЕКСТА ---
bot.on('text', async (ctx) => {
    if (!ctx.session) ctx.session = {};
    const text = ctx.message.text;
    const userId = ctx.from.id.toString();
    
    if (userId === ADMIN_ID) {
        if (ctx.session.waitingForBroadcast) {
            ctx.session.waitingForBroadcast = false;
            await ctx.reply('📢 Начинаю рассылку...');
            let sent = 0; let failed = 0;
            const users = await db.all('SELECT id FROM users');
            for (const u of users) { try { await bot.telegram.sendMessage(u.id, text, { parse_mode: 'HTML' }); sent++; await new Promise(r => setTimeout(r, 55)); } catch(e) { failed++; } }
            return ctx.reply(`✅ Отправлено: ${sent}\nНе доставлено: ${failed}`);
        }
        if (ctx.session.waitingForPremiumId) {
            ctx.session.waitingForPremiumId = false;
            const targetId = text.trim();
            if (!await db.get('SELECT id FROM users WHERE id = ?', [targetId])) return ctx.reply('❌ Не найден.');
            await db.run('UPDATE users SET is_premium = 1, premium_expiry = 0 WHERE id = ?', [targetId]);
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
    const msgId = await addMessage(ctx.session.targetId, ctx.session.sender_text, ctx.session.sender_name, ctx.session.sender_photo, is_open, ctx.session.mood, ctx.from.id.toString());
    ctx.session = {};
    await ctx.reply(`✅ Шёпот доставлен!`, getMainMenu());
    const moodEmoji = (ctx.session?.mood === 'crush') ? '❤️' : '🤫';
    try { await bot.telegram.sendMessage(ctx.session.targetId, `${moodEmoji} <b>Тебе пришел новый шёпот!</b>\n\n⏳ <i>Он удалится через 24 часа!</i>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📬 Прочитать', `read_${msgId}`)]]) }); } catch (e) {}
}

// === ЧТЕНИЕ СООБЩЕНИЙ (С ЖЕСТКИМ ПЕЙВОЛОМ) ===
bot.action(/^read_(.+)$/, async (ctx) => { const msg = await getMessageById(ctx.match[1]); if (!msg) return ctx.answerCbQuery('Устарело'); await showSingleMessage(ctx, msg); });

async function showNextMessage(ctx) { 
    if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Всё прочитано!', { ...getMainMenu() }); 
    const msgId = ctx.session.msgQueue.shift(); 
    const msg = await getMessageById(msgId); 
    if (!msg) return showNextMessage(ctx);
    await showSingleMessage(ctx, msg);
}

async function showSingleMessage(ctx, msg) {
    const userId = ctx.from.id.toString();
    await registerUser(userId, ctx.from.username, ctx.from.first_name);
    const user = await db.get('SELECT * FROM users WHERE id = ?', [userId]);
    const isPremium = isUserPremium(user); 
    const hasAccess = msg.is_open || isPremium || msg.is_revealed;

    if (!isPremium && user.free_reads_left <= 0 && !msg.is_open && !hasAccess) {
        ctx.answerCbQuery();
        return ctx.reply(`🔒 <b>Бесплатные чтения закончились!</b>\n\nЧтобы прочитать, нужен 1 Ключ или Премиум.\n\n⏳ <i>Это сообщение удалится через 24 часа!</i>`, {
            parse_mode: 'HTML',
            ...Markup.inlineKeyboard([
                [Markup.button.callback('🗝️ Использовать 1 Ключ', `pay_read_key_${msg.id}`)],
                [Markup.button.callback('👑 Премиум', 'shop_premium')],
                [Markup.button.callback('👥 Получить ключ бесплатно', 'link_default')]
            ])
        });
    }

    if (!isPremium && user.free_reads_left > 0 && !msg.is_open && !hasAccess) {
        await db.run('UPDATE users SET free_reads_left = free_reads_left - 1 WHERE id = ?', [userId]);
    }

    const reactionKeyboard = Markup.inlineKeyboard([[Markup.button.callback('❤️', `react_❤️_${msg.id}`), Markup.button.callback('😂', `react_😂_${msg.id}`), Markup.button.callback('😱', `react_😱_${msg.id}`)], [Markup.button.callback('➡️ Далее', 'skip_msg')]]);

    if (hasAccess) { 
        if (!msg.is_revealed && !msg.is_open) await revealMessage(msg.id);
        ctx.answerCbQuery(); 
        ctx.replyWithPhoto(msg.sender_photo, { caption: `📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, parse_mode: 'HTML', ...reactionKeyboard }).catch(() => { ctx.reply(`📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, { parse_mode: 'HTML', ...reactionKeyboard }); });
    } else { 
        ctx.answerCbQuery(); 
        ctx.reply(`📩 <b>Анонимное послание:</b>\n"${msg.text}"\n\n🎭 <i>Автор скрыт. Выбери, как прочитать:</i>`, { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([[Markup.button.callback('👁 Бесплатно', `mark_read_${msg.id}`)], [Markup.button.callback('👻 Втайне (49 ₽)', `mark_ghost_${msg.id}`)]]) 
        }); 
    }
}

bot.action(/^mark_read_(.+)$/, async (ctx) => { 
    const msg = await getMessageById(ctx.match[1]); if (!msg) return ctx.answerCbQuery('Ошибка');
    await markAsRead(msg.id, false); ctx.answerCbQuery(); ctx.deleteMessage().catch(()=>{});
    if (msg.is_revealed || msg.is_open) return;
    ctx.reply(`📩 <b>Прочитано!</b>\n"${msg.text}"\n\n🎭 Узнать автора?`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
            [Markup.button.callback(`🗝️ 1 Ключ (${getFirstLetter(msg.sender_name)})`, `hint_1_${msg.id}`)],
            [Markup.button.callback(`🗝️ 2 Ключа (${getFirstAndLastLetter(msg.sender_name)})`, `hint_2_${msg.id}`)],
            [Markup.button.callback('💳 Раскрыть (149 ₽)', `buy_reveal_${msg.id}`)],
            [Markup.button.callback('👑 Премиум', 'shop_premium'), Markup.button.callback('➡️ Далее', 'skip_msg')]
        ]) 
    });
});

bot.action(/^mark_ghost_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; const user = await db.get('SELECT * FROM users WHERE id = ?', [ctx.from.id.toString()]); const msg = await getMessageById(msgId); if (!msg) return ctx.answerCbQuery('Ошибка');
    if (isUserPremium(user) || user.is_ghost) { await markAsRead(msgId, true); ctx.answerCbQuery('👻 Втайне!'); ctx.deleteMessage().catch(()=>{}); ctx.reply(`📩 <b>Прочитано втайне:</b>\n"${msg.text}"`, { parse_mode: 'HTML' }); return; }
    ctx.answerCbQuery(); ctx.reply(`👻 <b>Режим Призрака (49 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(49, `${ctx.from.id}_ghost_${msgId}`))], [Markup.button.callback('✅ Я оплатил', `check_ghost_${msgId}`)]]) });
});

bot.action(/^pay_read_key_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; const spent = await spendKeys(ctx.from.id.toString(), 1);
    if (spent) { ctx.answerCbQuery('Ключ использован!'); const msg = await getMessageById(msgId); if(msg) { await markAsRead(msgId, false); await showSingleMessage(ctx, msg); } } 
    else { ctx.answerCbQuery('У тебя 0 ключей! Пригласи друга.', true); }
});

bot.action(/^hint_1_(.+)$/, async (ctx) => { const msg = await getMessageById(ctx.match[1]); const spent = await spendKeys(ctx.from.id.toString(), 1); if(spent) await ctx.answerCbQuery(`Подсказка: ${msg.sender_name.charAt(0).toUpperCase()}***`, true); else await ctx.answerCbQuery('Мало ключей!', true); });
bot.action(/^hint_2_(.+)$/, async (ctx) => { const msg = await getMessageById(ctx.match[1]); const spent = await spendKeys(ctx.from.id.toString(), 2); if(spent) await ctx.answerCbQuery(`Подсказка: ${getFirstAndLastLetter(msg.sender_name)}`, true); else await ctx.answerCbQuery('Мало ключей!', true); });

bot.action(/^react_(.+?)_(.+)$/, async (ctx) => {
    const emoji = ctx.match[1]; const msgId = ctx.match[2]; const msg = await getMessageById(msgId); if (!msg) return ctx.answerCbQuery('Ошибка');
    await db.run('UPDATE messages SET reaction = ? WHERE id = ?', [emoji, msgId]); ctx.answerCbQuery('Отправлено!');
    if (msg.sender_id) bot.telegram.sendMessage(msg.sender_id, `💌 Твой шёпот вызвал реакцию: ${emoji}`).catch(()=>{});
    ctx.editMessageReplyMarkup({ inline_keyboard: [[Markup.button.callback('➡️ Далее', 'skip_msg')]] }).catch(()=>{});
});

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });

bot.action(/^reveal_guest_(.+)$/, async (ctx) => { ctx.answerCbQuery(); ctx.reply(`👀 <b>Узнать, кто заходил (99 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_guest_${ctx.match[1]}`))], [Markup.button.callback('✅ Я оплатил', `check_guest_${ctx.match[1]}`)]]) }); });

// === МАГАЗИН ===
bot.action('shop_keys', (ctx) => { ctx.answerCbQuery(); ctx.reply(`🗝️ <b>Покупка Ключей</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 3 Ключа (99 ₽)', generatePaymentLink(99, `${ctx.from.id}_keys_3`))], [Markup.button.callback('✅ Я оплатил 3', 'check_keys_3')], [Markup.button.url('💳 10 Ключей (249 ₽)', generatePaymentLink(249, `${ctx.from.id}_keys_10`))], [Markup.button.callback('✅ Я оплатил 10', 'check_keys_10')]]) }); });
bot.action('shop_premium', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('👑 3 дня (99 ₽)', 'shop_prem_3')], [Markup.button.callback('👑 1 мес (299 ₽)', 'shop_prem_30')], [Markup.button.callback('👑 Навсегда (799 ₽)', 'shop_prem_forever')]]) }); });

bot.action('shop_prem_3', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 3 дня (99 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_prem_3`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_3')]]) }); });
bot.action('shop_prem_30', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 1 мес (299 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(299, `${ctx.from.id}_prem_30`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_30')]]) }); });
bot.action('shop_prem_forever', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 Навсегда (799 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_prem_forever`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_forever')]]) }); });
bot.action(/^buy_reveal_(.+)$/, async (ctx) => { ctx.answerCbQuery(); ctx.reply(`🕵️ Раскрыть (149 ₽)`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${ctx.match[1]}`))], [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${ctx.match[1]}`)]]) }); });

// === ПРОВЕРКА ОПЛАТ ===
bot.action('check_keys_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_3`)) { await addKeys(ctx.from.id, 3); ctx.reply('🗝️ +3 Ключа!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_keys_10', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_10`)) { await addKeys(ctx.from.id, 10); ctx.reply('🗝️ +10 Ключей!'); } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.action('check_prem_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_3`)) { await db.run('UPDATE users SET is_premium = 1, premium_expiry = ? WHERE id = ?', [Date.now() + 3*24*60*60*1000, ctx.from.id.toString()]); ctx.reply('👑 Активирован на 3 дня!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_prem_30', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_30`)) { await db.run('UPDATE users SET is_premium = 1, premium_expiry = ? WHERE id = ?', [Date.now() + 30*24*60*60*1000, ctx.from.id.toString()]); ctx.reply('👑 Активирован на месяц!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_prem_forever', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_forever`)) { await db.run('UPDATE users SET is_premium = 1, premium_expiry = 0 WHERE id = ?', [ctx.from.id.toString()]); ctx.reply('👑 Активирован навсегда!'); } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.action(/^check_ghost_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_ghost_${ctx.match[1]}`)){ await markAsRead(ctx.match[1], true); ctx.reply('👻 Призрак применен!'); const msg = await getMessageById(ctx.match[1]); if(msg) ctx.reply(`📩 "${msg.text}"`, {parse_mode:'HTML'}); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action(/^check_guest_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_guest_${ctx.match[1]}`)){ const guest = await db.get('SELECT first_name FROM users WHERE id = ?', [ctx.match[1]]); ctx.reply(`👀 Гость: ${guest ? guest.first_name : 'Аноним'}`, {parse_mode:'HTML'}); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${ctx.match[1]}`)){ const m = await getMessageById(ctx.match[1]); if(m) { await revealMessage(m.id); ctx.replyWithPhoto(m.sender_photo, {caption: `👤 ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}).catch(()=>ctx.reply(`👤 ${m.sender_name}\n\n"${m.text}"`, {parse_mode:'HTML'})); if(m.sender_id) bot.telegram.sendMessage(m.sender_id, `👁 Твой шёпот раскрыли!`).catch(()=>{}); } } else { ctx.reply('❌ Оплата не найдена.'); } });

// === АДМИНКА ===
bot.command('admin', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.session = {}; ctx.reply('👑 Админка', { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📊 Стат', 'admin_stats')], [Markup.button.callback('📢 Рассылка', 'admin_broadcast')], [Markup.button.callback('👑 Premium', 'admin_grant_premium')]]) }); });
bot.action('admin_stats', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; await ctx.answerCbQuery(); const u = await db.get('SELECT COUNT(id) as count FROM users'); const m = await db.get('SELECT COUNT(id) as count FROM messages'); ctx.reply(`📊:\n👥 ${u.count}\n📬 ${m.count}`); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForPremiumId=true; ctx.reply('👑 ID:'); });

// === ЗАПУСК ===
connectDB().then(() => {
    bot.launch().then(() => console.log('🤖 Шёпот (SQLite Scale) запущен!')).catch(err => console.error(err));
}).catch(err => console.error('Ошибка БД:', err));

process.once('SIGINT', () => { bot.stop('SIGINT'); db.close(); });
process.once('SIGTERM', () => { bot.stop('SIGTERM'); db.close(); });
