require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

const BOT_TOKEN = process.env.BOT_TOKEN;
const YOOMONEY_WALLET = process.env.YOOMONEY_WALLET;
const YOOMONEY_API_TOKEN = process.env.YOOMONEY_API_TOKEN;
const ADMIN_ID = process.env.ADMIN_ID; 
const DB_FILE = './database.json';

const bot = new Telegraf(BOT_TOKEN);

// === ВСТРОЕННАЯ СЕССИЯ ===
const sessionStore = new Map();
const sessionMiddleware = async (ctx, next) => {
    const key = ctx.from ? ctx.from.id.toString() : 'default';
    ctx.session = sessionStore.get(key) || {};
    await next();
    sessionStore.set(key, ctx.session);
};
bot.use(sessionMiddleware);

// === БАЗА ДАННЫХ ===
let db = { users: {}, messages: {}, used_payments: {} };
if (fs.existsSync(DB_FILE)) {
    try {
        const loadedData = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        db.users = loadedData.users || {};
        db.used_payments = loadedData.used_payments || {};
        db.messages = loadedData.messages || {};
        
        // Миграция БД
        Object.keys(db.users).forEach(id => { 
            if (db.users[id].keys === undefined) db.users[id].keys = 0; 
            if (db.users[id].is_ghost === undefined) db.users[id].is_ghost = false; // Флаг призрака
        });
        Object.keys(db.messages).forEach(id => { 
            if (!db.messages[id].sender_id) db.messages[id].sender_id = null; 
            if (!db.messages[id].mood) db.messages[id].mood = 'default'; 
            if (db.messages[id].is_read_ghost === undefined) db.messages[id].is_read_ghost = false;
        });
    } catch (e) { console.error('Ошибка загрузки БД:', e); }
}

let saveTimeout = null;
function scheduleSave() {
    if (!saveTimeout) {
        saveTimeout = setTimeout(() => {
            fs.writeFile(DB_FILE, JSON.stringify(db, null, 2), (err) => { if (err) console.error('Ошибка сохранения БД:', err); }); 
            saveTimeout = null; 
        }, 2000);
    }
}

function gracefulShutdown() {
    console.log('Сохранение базы данных перед выключением...');
    try { fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2)); } catch (e) { console.error('Ошибка сохранения:', e); }
    process.exit();
}

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    const userId = tg_id.toString();
    if (!db.users[userId]) { 
        db.users[userId] = { username, first_name, is_premium: false, premium_expiry: 0, ref_count: 0, invited_by: null, keys: 1, is_ghost: false }; 
        scheduleSave(); 
    }
}

function generateId() { return Date.now().toString(36) + Math.random().toString(36).slice(2); }

function addMessage(target_id, text, sender_name, sender_photo, is_open, mood, sender_id) { 
    const id = generateId(); 
    db.messages[id] = { id, target_id: target_id.toString(), text, sender_name, sender_photo, is_read: false, is_read_ghost: false, is_revealed: false, is_open, mood, sender_id: sender_id.toString(), reaction: null, created_at: Date.now() }; 
    scheduleSave(); 
    return id; 
}

function getUnreadMessages(target_id) { 
    const tid = target_id.toString();
    return Object.values(db.messages).filter(m => m.target_id === tid && !m.is_read && !m.is_read_ghost).sort((a, b) => b.created_at - a.created_at); 
}

function getMessageById(id) { return db.messages[id]; }
function markAsRead(id, isGhost) { 
    const m = db.messages[id]; 
    if (m) { 
        if (isGhost) m.is_read_ghost = true; 
        else m.is_read = true; 
        scheduleSave(); 
    } 
}
function revealMessage(id) { const m = db.messages[id]; if (m) { m.is_revealed = true; scheduleSave(); } }

function addKeys(userId, amount) { if (db.users[userId]) { db.users[userId].keys += amount; scheduleSave(); } }
function spendKeys(userId, amount) { if (db.users[userId] && db.users[userId].keys >= amount) { db.users[userId].keys -= amount; scheduleSave(); return true; } return false; }

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
    if (db.used_payments[label]) return false;
    try { 
        const p = new URLSearchParams(); p.append('label', label); p.append('type', 'in'); 
        const r = await fetch('https://yoomoney.ru/api/operation-history', { method: 'POST', headers: { 'Authorization': `Bearer ${YOOMONEY_API_TOKEN}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: p.toString() }); 
        const d = await r.json(); 
        const isSuccess = d.operations && d.operations.some(o => o.status === 'success');
        if (isSuccess) { db.used_payments[label] = true; scheduleSave(); }
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
        if (refId !== userId && db.users[refId]) {
            if (!db.users[userId].invited_by) {
                db.users[userId].invited_by = refId;
                db.users[refId].ref_count++;
                addKeys(refId, 1);
                scheduleSave();
                bot.telegram.sendMessage(refId, '👥 По твоей ссылке перешел друг! Твой подарок: 🗝️ +1 Ключ').catch(()=>{});
            }
        }
        return ctx.reply('👋 Добро пожаловать! Тебя пригласили в Шёпот.', { parse_mode: 'HTML', ...getMainMenu() });
    }

    if (payload && payload.startsWith('w_')) {
        const parts = payload.replace('w_', '').split('_mood_');
        const targetId = parts[0];
        const mood = parts[1] || 'default';
        
        const targetUser = db.users[targetId];
        if (!targetUser) return ctx.reply('Этот человек еще не в Шёпоте :(');
        
        // 🔥 МОНЕТИЗАЦИЯ ЭГО: Уведомление о госте
        const guestName = ctx.from.first_name || 'Аноним';
        bot.telegram.sendMessage(targetId, 
            `👀 <b>Внимание!</b>\nКто-то только что открывал твою ссылку, чтобы написать шёпот...`, 
            {
                parse_mode: 'HTML',
                ...Markup.inlineKeyboard([
                    [Markup.button.callback('🕵️ Узнать, кто заходил (99 ₽)', `reveal_guest_${userId}`)]
                ])
            }
        ).catch(()=>{});

        const moodData = MOODS[mood] || MOODS.default;
        ctx.session = { targetId: targetId, sender_step: 'ask_name', mood: mood };
        
        return ctx.reply(
            `🤫 <b>${moodData.text} для ${targetUser.first_name}</b>\n\n👤 Напиши свое имя:`,
            { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
        );
    }

    ctx.session = {};
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    await ctx.reply(
        `🤫 <b>Добро пожаловать в Шёпот!</b>\n\n📩 Читать тексты — <b>бесплатно</b>.\n🎭 Авторы скрыты... Используй 🗝️ Ключи или Премиум!\n\n🔗 Поделись ссылкой, чтобы получать шёпоты!`,
        { parse_mode: 'HTML', ...getMainMenu() }
    );
});

// --- КНОПКИ МЕНЮ ---
bot.hears('🗝️ Ключи и Ссылка', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    const user = db.users[userId];
    ctx.reply(
        `🗝️ У тебя: <b>${user.keys} Ключей</b>\n\n1 друг по ссылке = 1 Ключ!\n\n🔗 <b>Выбери ссылку:</b>`,
        { 
            parse_mode: 'HTML',
            ...Markup.inlineKeyboard([
                [Markup.button.callback('🤫 Обычный Шёпот', 'link_default')],
                [Markup.button.callback('😈 Исповедь', 'link_confession'), Markup.button.callback('🔥 Откровенный вопрос', 'link_truth')],
                [Markup.button.callback('❤️ Симпатия', 'link_crush')],
                [Markup.button.callback('🛒 Купить Ключи (Выгодные наборы!)', 'shop_keys')]
            ])
        }
    );
});

bot.hears('🤫 Шёпоты', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    if (!db.users[userId]) registerUser(userId, ctx.from.username, ctx.from.first_name);
    const msgs = getUnreadMessages(userId);
    if (msgs.length === 0) return ctx.reply('📭 Шёпотов пока нет... Поделись ссылкой!');
    ctx.session.msgQueue = msgs.map(m => m.id);
    showNextMessage(ctx);
});

bot.hears('👑 Премиум', (ctx) => {
    ctx.session = {};
    ctx.reply(
        `👑 <b>Премиум-Шёпот</b>\n\n✅ Все авторы раскрываются бесплатно\n✅ Режим Призрака 👻 навсегда (читай втайне)\n\nВыбери тариф:`,
        { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([
                [Markup.button.callback('👑 3 дня (99 ₽)', 'shop_prem_3')],
                [Markup.button.callback('👑 1 месяц (299 ₽)', 'shop_prem_30')],
                [Markup.button.callback('👑 Навсегда (799 ₽)', 'shop_prem_forever')]
            ])
        }
    );
});

bot.hears('👤 Профиль', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    if (!db.users[userId]) registerUser(userId, ctx.from.username, ctx.from.first_name);
    const user = db.users[userId];
    const premiumStatus = isUserPremium(user) ? '👑 Активен' : '❌ Нет';
    const ghostStatus = user.is_ghost ? '👻 Да' : '❌ Нет';
    ctx.reply(
        `👤 <b>Мой профиль</b>\n\n🤫 Имя: <b>${ctx.from.first_name}</b>\n🗝️ Ключи: <b>${user.keys}</b>\n👻 Призрак: ${ghostStatus}\n👑 Премиум: ${premiumStatus}\n👥 Приглашено: <b>${user.ref_count}</b>`,
        { parse_mode: 'HTML' }
    );
});

// === ГЕНЕРАЦИЯ ССЫЛОК ===
bot.action(/^link_(.+)$/, (ctx) => {
    const mood = ctx.match[1];
    const userId = ctx.from.id.toString();
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}_mood_${mood}`;
    const refLink = `https://t.me/${ctx.botInfo.username}?start=r_${userId}`;
    ctx.answerCbQuery();
    ctx.reply(
        `🔗 <b>Твоя ссылка (${MOODS[mood].title}):</b>\n<code>${link}</code>\n\n👥 <b>Реферальная (за друга 🗝️):</b>\n<code>${refLink}</code>`,
        { parse_mode: 'HTML' }
    );
});

// --- ОБРАБОТКА ФОТО И ДОКУМЕНТОВ ---
bot.on('photo', async (ctx) => {
    if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
    ctx.session.sender_photo = ctx.message.photo[ctx.message.photo.length - 1].file_id;
    ctx.session.sender_step = 'ask_message';
    await ctx.reply('✅ Фото получено! Теперь напиши послание или вопрос:');
});

bot.on('document', async (ctx) => {
    if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
    ctx.session.sender_photo = ctx.message.document.thumb ? ctx.message.document.thumb.file_id : ctx.message.document.file_id;
    ctx.session.sender_step = 'ask_message';
    await ctx.reply('✅ Фото получено! Теперь напиши послание или вопрос:');
});

// --- ОБРАБОТКА ТЕКСТА ---
bot.on('text', async (ctx) => {
    if (!ctx.session) ctx.session = {};
    const text = ctx.message.text;
    const userId = ctx.from.id.toString();
    
    if (userId === ADMIN_ID) {
        if (ctx.session.waitingForBroadcast) {
            ctx.session.waitingForBroadcast = false;
            const users = Object.keys(db.users); let sent = 0; let failed = 0;
            await ctx.reply('📢 Начинаю рассылку...');
            for (const id of users) { try { await bot.telegram.sendMessage(id, text, { parse_mode: 'HTML' }); sent++; await new Promise(r => setTimeout(r, 55)); } catch(e) { failed++; } }
            return ctx.reply(`✅ Отправлено: ${sent}\nНе доставлено: ${failed}`);
        }
        if (ctx.session.waitingForPremiumId) {
            ctx.session.waitingForPremiumId = false;
            const targetId = text.trim();
            if (!db.users[targetId]) return ctx.reply('❌ Не найден.');
            db.users[targetId].is_premium = true; db.users[targetId].premium_expiry = 0; scheduleSave();
            return ctx.reply(`✅ Premium выдан!`);
        }
    }

    if (ctx.session.sender_step === 'ask_photo') return ctx.reply('📸 Нужно прислать фото. Попробуй еще раз.');
    if (ctx.session.sender_step === 'ask_name') {
        ctx.session.sender_name = text;
        ctx.session.sender_step = 'ask_photo';
        return ctx.reply('📸 Прикрепи свое фото (картинкой или файлом).');
    }
    if (ctx.session.sender_step === 'ask_message') {
        if (text.length > 200) return ctx.reply('❌ Максимум 200 символов! Сократи:');
        ctx.session.sender_text = text;
        ctx.session.sender_step = 'choose_mode';
        return ctx.reply(
            `📝 Послание готово: "${text}"\n\nВыбери, как отправить:`,
            { parse_mode: 'HTML', ...Markup.inlineKeyboard([ [Markup.button.callback('🤫 Анонимно', 'send_anon')], [Markup.button.callback('👤 Открыто', 'send_open')] ]) }
        );
    }
});

bot.action('send_anon', (ctx) => { sendMessage(ctx, false); });
bot.action('send_open', (ctx) => { sendMessage(ctx, true); });

async function sendMessage(ctx, is_open) {
    if (!ctx.session || !ctx.session.targetId) return ctx.answerCbQuery('Ошибка сессии');
    const targetId = ctx.session.targetId;
    const mood = ctx.session.mood || 'default';
    const msgId = addMessage(targetId, ctx.session.sender_text, ctx.session.sender_name, ctx.session.sender_photo, is_open, mood, ctx.from.id.toString());

    ctx.session = {};
    await ctx.reply(`✅ Шёпот доставлен!`, getMainMenu());
    
    const moodEmoji = mood === 'crush' ? '❤️' : mood === 'confession' ? '😈' : mood === 'truth' ? '🔥' : '🤫';
    try {
        await bot.telegram.sendMessage(targetId, `${moodEmoji} <b>Тебе пришел новый шёпот!</b>`, { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([[Markup.button.callback('📬 Прочитать', `read_${msgId}`)]])
        });
    } catch (e) {}
}

// === ЧТЕНИЕ СООБЩЕНИЙ (С РЕЖИМОМ ПРИЗРАКА) ===
bot.action(/^read_(.+)$/, (ctx) => { 
    const msgId = ctx.match[1]; 
    const msg = getMessageById(msgId); 
    if (!msg) return ctx.answerCbQuery('Устарело'); 
    // Не помечаем как прочитанное сразу! Даем выбор.
    showSingleMessage(ctx, msg);
});

function showNextMessage(ctx) { 
    if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) return ctx.reply('📭 Всё прочитано!', { ...getMainMenu() }); 
    const msgId = ctx.session.msgQueue.shift(); 
    const msg = getMessageById(msgId); 
    if (!msg) return showNextMessage(ctx);
    showSingleMessage(ctx, msg);
}

function showSingleMessage(ctx, msg) {
    const userId = ctx.from.id.toString();
    if (!db.users[userId]) registerUser(userId, ctx.from.username, ctx.from.first_name);
    const user = db.users[userId];
    const isPremium = isUserPremium(user); 
    const hasAccess = msg.is_open || isPremium || msg.is_revealed;

    // Кнопки чтения (Призрак или Обычное)
    const readKeyboard = Markup.inlineKeyboard([
        [Markup.button.callback('👁 Прочитать (отправитель увидит)', `mark_read_${msg.id}`)],
        [Markup.button.callback('👻 Прочитать как Призрак (49 ₽)', `mark_ghost_${msg.id}`)]
    ]);

    // Меню реакций
    const reactionKeyboard = Markup.inlineKeyboard([
        [Markup.button.callback('❤️', `react_❤️_${msg.id}`), Markup.button.callback('😂', `react_😂_${msg.id}`), Markup.button.callback('😱`, `react_😱_${msg.id}`)],
        [Markup.button.callback('➡️ Далее', 'skip_msg')]
    ]);

    if (hasAccess) { 
        if (!msg.is_revealed && !msg.is_open) revealMessage(msg.id);
        ctx.answerCbQuery(); 
        ctx.replyWithPhoto(msg.sender_photo, { 
            caption: `📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, 
            parse_mode: 'HTML',
            ...reactionKeyboard
        }).catch(() => {
            ctx.reply(`📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, { parse_mode: 'HTML', ...reactionKeyboard });
        });
    } else { 
        ctx.answerCbQuery(); 
        ctx.reply(
            `📩 <b>Анонимное послание:</b>\n"${msg.text}"\n\n🎭 <i>Автор скрыт. Выбери, как прочитать:</i>`, 
            { 
                parse_mode: 'HTML', 
                ...Markup.inlineKeyboard([
                    [Markup.button.callback('👁 Прочитать (бесплатно)', `mark_read_${msg.id}`)],
                    [Markup.button.callback('👻 Прочитать втайне (49 ₽)', `mark_ghost_${msg.id}`)],
                ]) 
            }
        ); 
    }
}

// Обработка кнопок чтения
bot.action(/^mark_read_(.+)$/, (ctx) => { 
    const msgId = ctx.match[1]; 
    const msg = getMessageById(msgId); 
    if (!msg) return ctx.answerCbQuery('Ошибка');
    markAsRead(msg.id, false);
    ctx.answerCbQuery();
    ctx.deleteMessage().catch(()=>{});
    
    if (msg.is_revealed || msg.is_open) return; // Если уже раскрыто - ничего не делаем
    
    // Показываем меню подсказок
    ctx.reply(
        `📩 <b>Текст прочитан! Отправитель увидит это.</b>\n"${msg.text}"\n\n🎭 Хочешь узнать автора?`, 
        { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([
                [Markup.button.callback(`🗝️ 1 Ключ (Буква: ${getFirstLetter(msg.sender_name)})`, `hint_1_${msg.id}`)],
                [Markup.button.callback(`🗝️ 2 Ключа (Буквы: ${getFirstAndLastLetter(msg.sender_name)})`, `hint_2_${msg.id}`)],
                [Markup.button.callback('💳 Раскрыть полностью (149 ₽)', `buy_reveal_${msg.id}`)],
                [Markup.button.callback('👑 Премиум', 'shop_premium'), Markup.button.callback('➡️ Далее', 'skip_msg')]
            ]) 
        }
    );
});

bot.action(/^mark_ghost_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; 
    const userId = ctx.from.id.toString();
    const user = db.users[userId];
    const msg = getMessageById(msgId); 
    if (!msg) return ctx.answerCbQuery('Ошибка');

    // Если премиум или уже куплен призрак — бесплатно
    if (isUserPremium(user) || user.is_ghost) {
        markAsRead(msg.id, true);
        ctx.answerCbQuery('👻 Прочитано втайне!');
        ctx.deleteMessage().catch(()=>{});
        ctx.reply(`📩 <b>Текст прочитан втайне! Отправитель ничего не узнает.</b>\n"${msg.text}"`, { parse_mode: 'HTML' });
        return;
    }

    // Иначе предлагаем оплатить
    ctx.answerCbQuery();
    ctx.reply(
        `👻 <b>Режим Призрака (49 ₽)</b>\nОтправитель не увидит, что ты читал сообщение.`,
        { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([
                [Markup.button.url('💳 Оплатить', generatePaymentLink(49, `${userId}_ghost_${msgId}`))], 
                [Markup.button.callback('✅ Я оплатил', `check_ghost_${msgId}`)]
            ]) 
        }
    );
});

// Покупка подсказок за КЛЮЧИ
bot.action(/^hint_1_(.+)$/, async (ctx) => {
    const msgId = ctx.match[1];
    const userId = ctx.from.id.toString();
    if (spendKeys(userId, 1)) {
        const msg = getMessageById(msgId);
        await ctx.answerCbQuery(`Подсказка: Имя начинается на ${msg.sender_name.charAt(0).toUpperCase()}`, true);
    } else {
        await ctx.answerCbQuery('Недостаточно ключей! Купи или пригласи друга.', true);
    }
});

bot.action(/^hint_2_(.+)$/, async (ctx) => {
    const msgId = ctx.match[1];
    const userId = ctx.from.id.toString();
    if (spendKeys(userId, 2)) {
        const msg = getMessageById(msgId);
        await ctx.answerCbQuery(`Подсказка: ${getFirstAndLastLetter(msg.sender_name)}`, true);
    } else {
        await ctx.answerCbQuery('Недостаточно ключей! Купи или пригласи друга.', true);
    }
});

// Обработка реакций
bot.action(/^react_(.+?)_(.+)$/, async (ctx) => {
    const emoji = ctx.match[1];
    const msgId = ctx.match[2];
    const msg = getMessageById(msgId);
    if (!msg) return ctx.answerCbQuery('Ошибка');

    msg.reaction = emoji;
    scheduleSave();
    ctx.answerCbQuery('Реакция отправлена!');

    if (msg.sender_id) {
        bot.telegram.sendMessage(msg.sender_id, `💌 Твой шёпот вызвал реакцию: ${emoji}`).catch(()=>{});
    }
    ctx.editMessageReplyMarkup({ inline_keyboard: [[Markup.button.callback('➡️ Далее', 'skip_msg')]] }).catch(()=>{});
});

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });

// === МОНЕТИЗАЦИЯ: ГОСТЬ ПРОФИЛЯ ===
bot.action(/^reveal_guest_(.+)$/, async (ctx) => {
    const guestId = ctx.match[1];
    const userId = ctx.from.id.toString();
    ctx.answerCbQuery();
    ctx.reply(
        `👀 <b>Узнать, кто заходил (99 ₽)</b>`,
        { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([
                [Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${userId}_guest_${guestId}`))], 
                [Markup.button.callback('✅ Я оплатил', `check_guest_${guestId}`)]
            ]) 
        }
    );
});

// === МАГАЗИН ===
bot.action('shop_keys', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `🗝️ <b>Покупка Ключей</b>\n\nИспользуй их, чтобы узнавать буквы имен!`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.url('💳 3 Ключа (99 ₽)', generatePaymentLink(99, `${ctx.from.id}_keys_3`))], 
          [Markup.button.callback('✅ Я оплатил 3 Ключа', 'check_keys_3')],
          [Markup.button.url('💳 10 Ключей (249 ₽) - ВЫГОДА!', generatePaymentLink(249, `${ctx.from.id}_keys_10`))], 
          [Markup.button.callback('✅ Я оплатил 10 Ключей', 'check_keys_10')]
        ]) 
      }
    ); 
});

bot.action('shop_premium', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(`👑 <b>Премиум-Шёпот</b>\n\n✅ Все авторы раскрываются бесплатно\n✅ Режим Призрака 👻 навсегда`, { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.callback('👑 3 дня (99 ₽)', 'shop_prem_3')],
          [Markup.button.callback('👑 1 месяц (299 ₽)', 'shop_prem_30')],
          [Markup.button.callback('👑 Навсегда (799 ₽)', 'shop_prem_forever')]
        ])
    }); 
});

bot.action('shop_prem_3', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум 3 дня (99 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(99, `${ctx.from.id}_prem_3`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_3')]]) }); });
bot.action('shop_prem_30', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум 1 месяц (299 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(299, `${ctx.from.id}_prem_30`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_30')]]) }); });
bot.action('shop_prem_forever', (ctx) => { ctx.answerCbQuery(); ctx.reply(`👑 <b>Премиум навсегда (799 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(799, `${ctx.from.id}_prem_forever`))], [Markup.button.callback('✅ Я оплатил', 'check_prem_forever')]]) }); });

bot.action(/^buy_reveal_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; ctx.answerCbQuery(); 
    ctx.reply(`🕵️ <b>Раскрыть полностью (149 ₽)</b>`, { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_${id}`))], [Markup.button.callback('✅ Я оплатил', `check_reveal_specific_${id}`)]]) }); 
});

// === ПРОВЕРКА ОПЛАТ ===
bot.action('check_keys_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_3`)) { addKeys(ctx.from.id, 3); ctx.reply('🗝️ +3 Ключа!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_keys_10', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_keys_10`)) { addKeys(ctx.from.id, 10); ctx.reply('🗝️ +10 Ключей!'); } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.action('check_prem_3', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_3`)) { const u = db.users[ctx.from.id.toString()]; u.is_premium = true; u.premium_expiry = Date.now() + 3*24*60*60*1000; scheduleSave(); ctx.reply('👑 Премиум на 3 дня активирован!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_prem_30', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_30`)) { const u = db.users[ctx.from.id.toString()]; u.is_premium = true; u.premium_expiry = Date.now() + 30*24*60*60*1000; scheduleSave(); ctx.reply('👑 Премиум на месяц активирован!'); } else { ctx.reply('❌ Оплата не найдена.'); } });
bot.action('check_prem_forever', async (ctx) => { await ctx.answerCbQuery('Проверяю...'); if (await checkYooMoneyPayment(`${ctx.from.id}_prem_forever`)) { const u = db.users[ctx.from.id.toString()]; u.is_premium = true; u.premium_expiry = 0; scheduleSave(); ctx.reply('👑 Премиум навсегда активирован!'); } else { ctx.reply('❌ Оплата не найдена.'); } });

bot.action(/^check_ghost_(.+)$/, async (ctx) => { 
    const msgId = ctx.match[1]; 
    await ctx.answerCbQuery('Проверяю...'); 
    if(await checkYooMoneyPayment(`${ctx.from.id}_ghost_${msgId}`)){ 
        markAsRead(msgId, true);
        ctx.reply('👻 Режим Призрака применен! Отправитель не узнает, что ты читал.');
        const msg = getMessageById(msgId);
        ctx.reply(`📩 <b>Текст:</b>\n"${msg.text}"`, { parse_mode: 'HTML' });
    } else { ctx.reply('❌ Оплата не найдена.'); } 
});

bot.action(/^check_guest_(.+)$/, async (ctx) => { 
    const guestId = ctx.match[1]; 
    await ctx.answerCbQuery('Проверяю...'); 
    if(await checkYooMoneyPayment(`${ctx.from.id}_guest_${guestId}`)){ 
        const guestUser = db.users[guestId];
        const name = guestUser ? guestUser.first_name : 'Аноним';
        ctx.reply(`👀 <b>Твой гость:</b> ${name}`, { parse_mode: 'HTML' });
    } else { ctx.reply('❌ Оплата не найдена.'); } 
});

bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    await ctx.answerCbQuery('Проверяю...'); 
    if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${id}`)){ 
        const m = getMessageById(id); 
        if(m) { 
            revealMessage(m.id); 
            ctx.replyWithPhoto(m.sender_photo, { caption: `👤 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}).catch(() => { ctx.reply(`👤 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, { parse_mode:'HTML' }); });
            if(m.sender_id) bot.telegram.sendMessage(m.sender_id, `👁 Твой шёпот был раскрыт за деньги!`).catch(()=>{});
        }
    } else { ctx.reply('❌ Оплата не найдена.'); } 
});

// === АДМИНКА ===
bot.command('admin', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.session = {}; ctx.reply('👑 Админка', { parse_mode: 'HTML', ...Markup.inlineKeyboard([[Markup.button.callback('📊 Стат', 'admin_stats')], [Markup.button.callback('📢 Рассылка', 'admin_broadcast')], [Markup.button.callback('👑 Premium', 'admin_grant_premium')], [Markup.button.callback('🧹 Очистить', 'admin_clear_msgs')]]) }); });
bot.action('admin_stats', async (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; await ctx.answerCbQuery(); ctx.reply(`📊:\n👥 ${Object.keys(db.users).length}\n📬 ${Object.keys(db.messages).length}`); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); ctx.session.waitingForPremiumId=true; ctx.reply('👑 ID:'); });
bot.action('admin_clear_msgs', (ctx) => { if (ctx.from.id.toString() !== ADMIN_ID) return; ctx.answerCbQuery(); db.messages={}; scheduleSave(); ctx.reply('🧹 Очищено!'); });

// === ЗАПУСК ===
bot.launch().then(() => console.log('🤖 Шёпот (Money Machine) запущен!')).catch(err => console.error(err));
process.once('SIGINT', () => { bot.stop('SIGINT'); gracefulShutdown(); });
process.once('SIGTERM', () => { bot.stop('SIGTERM'); gracefulShutdown(); });
