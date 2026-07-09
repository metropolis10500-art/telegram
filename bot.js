require('dotenv').config();
const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

const BOT_TOKEN = process.env.BOT_TOKEN;
const YOOMONEY_WALLET = process.env.YOOMONEY_WALLET;
const YOOMONEY_API_TOKEN = process.env.YOOMONEY_API_TOKEN;
const ADMIN_ID = process.env.ADMIN_ID; // Оставляем строкой для удобства сравнения
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
// ========================

// === БАЗА ДАННЫХ ===
let db = { users: {}, messages: {}, used_payments: {} };
if (fs.existsSync(DB_FILE)) {
    try {
        const loadedData = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        db.users = loadedData.users || {};
        db.used_payments = loadedData.used_payments || {};
        if (Array.isArray(loadedData.messages)) { 
            loadedData.messages.forEach(m => db.messages[m.id] = m); 
        } else { 
            db.messages = loadedData.messages || {}; 
        }
    } catch (e) { 
        console.error('Ошибка загрузки БД:', e); 
    }
}

let saveTimeout = null;
function scheduleSave() {
    if (!saveTimeout) {
        saveTimeout = setTimeout(() => {
            fs.writeFile(DB_FILE, JSON.stringify(db, null, 2), (err) => { 
                if (err) console.error('Ошибка сохранения БД:', err); 
            }); 
            saveTimeout = null; 
        }, 2000);
    }
}

function gracefulShutdown() {
    console.log('Сохранение базы данных перед выключением...');
    try {
        fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
    } catch (e) {
        console.error('Ошибка принудительного сохранения:', e);
    }
    process.exit();
}

setInterval(() => {
    const threeDaysAgo = Date.now() - 3 * 24 * 60 * 60 * 1000;
    let deletedCount = 0;
    Object.keys(db.messages).forEach(id => { 
        if (db.messages[id].is_read && db.messages[id].created_at < threeDaysAgo) { 
            delete db.messages[id]; 
            deletedCount++; 
        } 
    });
    if (deletedCount > 0) { 
        console.log(`Удалено ${deletedCount} старых сообщений`); 
        scheduleSave(); 
    }
}, 3600000);

// === ФУНКЦИИ БАЗЫ ===
function registerUser(tg_id, username, first_name) {
    const userId = tg_id.toString(); // Приводим к строке
    if (!db.users[userId]) { 
        db.users[userId] = { username, first_name, is_premium: false, premium_expiry: 0, ref_count: 0, invited_by: null }; 
        scheduleSave(); 
    }
}

function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

function addMessage(target_id, text, sender_name, sender_photo, is_open) { 
    const id = generateId(); 
    db.messages[id] = { id, target_id: target_id.toString(), text, sender_name, sender_photo, is_read: false, is_revealed: false, is_open: is_open, created_at: Date.now() }; 
    scheduleSave(); 
    return id; 
}

function getUnreadMessages(target_id) { 
    const tid = target_id.toString();
    return Object.values(db.messages).filter(m => m.target_id === tid && !m.is_read).sort((a, b) => b.created_at - a.created_at); 
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
    if (db.used_payments[label]) return false;

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
        const isSuccess = d.operations && d.operations.some(o => o.status === 'success');
        
        if (isSuccess) {
            db.used_payments[label] = true;
            scheduleSave();
        }
        return isSuccess;
    } catch (e) { 
        console.error('YooMoney API Error:', e);
        return false; 
    } 
}

function isUserPremium(user) {
    if (!user) return false; // Защита от undefined
    return user.is_premium && (user.premium_expiry === 0 || user.premium_expiry > Date.now());
}

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
                scheduleSave();
                bot.telegram.sendMessage(refId, '👥 По твоей ссылке перешел друг!').catch(()=>{});
            }
        }
        return ctx.reply('👋 Добро пожаловать! Тебя пригласили в Шёпот.', { parse_mode: 'HTML', ...getMainMenu() });
    }

    if (payload && payload.startsWith('w_')) {
        const targetId = payload.replace('w_', '');
        const targetUser = db.users[targetId];
        if (!targetUser) return ctx.reply('Этот человек еще не в Шёпоте :(');
        
        ctx.session = { targetId: targetId, sender_step: 'ask_name' };
        return ctx.reply(
            `🤫 <b>Напиши сообщение или вопрос для ${targetUser.first_name}</b>\n\n` +
            `Укажи свое имя и фото. Потом ты сможешь выбрать: отправить анонимно или открыто.\n\n` +
            `👤 Напиши свое имя:`,
            { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
        );
    }

    ctx.session = {};
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    const user = db.users[userId];
    const badge = isUserPremium(user) ? '👑' : '';
    
    await ctx.reply(
        `👋 <b>Добро пожаловать в Шёпот — 🤫 Анонимные сообщения и вопросы!</b>\n\n` +
        `Узнай, что скрывают твои друзья. Спрашивай и отвечай на вопросы. Они могут быть открытыми или анонимными ;)\n\n` +
        `📱 Кидай ссылку в Instagram, TikTok или VK. Друзья напишут то, что никогда не сказали бы в лицо!\n\n` +
        `📩 Тексты ты читаешь <b>бесплатно</b>.\n` +
        `🎭 Но анонимные авторы скрыты. Хочешь узнать, кто это и увидеть фото? Это доступно в Премиум!\n\n` +
        `🔗 <b>Твоя ссылка:</b>\n<code>${link}</code>`,
        { parse_mode: 'HTML', ...getMainMenu() }
    );
});

// --- КНОПКИ МЕНЮ ---
bot.hears('🔗 Моя ссылка', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    const link = `https://t.me/${ctx.botInfo.username}?start=w_${userId}`;
    const refLink = `https://t.me/${ctx.botInfo.username}?start=r_${userId}`;
    ctx.reply(
        `🔗 <b>Ссылка для соцсетей:</b>\n<code>${link}</code>\n\n` +
        `👥 <b>Реферальная ссылка:</b>\n<code>${refLink}</code>`,
        { parse_mode: 'HTML' }
    );
});

bot.hears('📬 Сообщения', (ctx) => {
    ctx.session = {};
    const userId = ctx.from.id.toString();
    if (!db.users[userId]) registerUser(userId, ctx.from.username, ctx.from.first_name); // Защита
    
    const msgs = getUnreadMessages(userId);
    if (msgs.length === 0) return ctx.reply('📭 Пока пусто... Поделись ссылкой!');
    ctx.session.msgQueue = msgs.map(m => m.id);
    showNextMessage(ctx);
});

bot.hears('💎 Премиум', (ctx) => {
    ctx.session = {};
    ctx.reply(
        `🎭 <b>Хочешь знать, кто тебе пишет?</b>\n\nВсе анонимные авторы скрыты. Выбери, как их раскрыть:`,
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
    ctx.session = {};
    const userId = ctx.from.id.toString();
    if (!db.users[userId]) registerUser(userId, ctx.from.username, ctx.from.first_name); // Защита от undefined
    
    const user = db.users[userId];
    const premiumStatus = isUserPremium(user) ? '👑 Активен' : '❌ Нет';
    ctx.reply(
        `👤 <b>Мой профиль</b>\n\n🤫 Имя: <b>${ctx.from.first_name}</b>\n👑 Премиум: ${premiumStatus}\n👥 Переходов по рефке: <b>${user.ref_count}</b>`,
        { parse_mode: 'HTML' }
    );
});

// --- ОБРАБОТКА ФОТО И ДОКУМЕНТОВ ---
bot.on('photo', async (ctx) => {
    if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
    const photoId = ctx.message.photo[ctx.message.photo.length - 1].file_id;
    ctx.session.sender_photo = photoId;
    ctx.session.sender_step = 'ask_message';
    await ctx.reply('✅ Фото получено! Теперь напиши послание или вопрос:');
});

bot.on('document', async (ctx) => {
    if (!ctx.session || ctx.session.sender_step !== 'ask_photo') return;
    const fileId = ctx.message.document.thumb ? ctx.message.document.thumb.file_id : ctx.message.document.file_id;
    ctx.session.sender_photo = fileId;
    ctx.session.sender_step = 'ask_message';
    await ctx.reply('✅ Фото получено! Теперь напиши послание или вопрос:');
});

// --- ОБРАБОТКА ТЕКСТА ---
bot.on('text', async (ctx) => {
    if (!ctx.session) ctx.session = {};
    const text = ctx.message.text;
    const userId = ctx.from.id.toString();
    
    // Админ-команды
    if (userId === ADMIN_ID) {
        if (ctx.session.waitingForBroadcast) {
            ctx.session.waitingForBroadcast = false;
            const users = Object.keys(db.users); 
            let sent = 0;
            let failed = 0;
            
            await ctx.reply('📢 Начинаю рассылку...');
            for (const id of users) { 
                try { 
                    await bot.telegram.sendMessage(id, text, { parse_mode: 'HTML' }); 
                    sent++; 
                    await new Promise(r => setTimeout(r, 55)); 
                } catch(e) { 
                    failed++;
                } 
            }
            return ctx.reply(`✅ Рассылка завершена!\nОтправлено: ${sent}\nНе доставлено: ${failed}`);
        }
        if (ctx.session.waitingForPremiumId) {
            ctx.session.waitingForPremiumId = false;
            const targetId = text.trim();
            if (!db.users[targetId]) return ctx.reply('❌ Пользователь не найден.');
            db.users[targetId].is_premium = true; 
            db.users[targetId].premium_expiry = 0;
            scheduleSave();
            return ctx.reply(`✅ Premium выдан пользователю ${targetId}!`);
        }
    }

    if (ctx.session.sender_step === 'ask_photo') {
        return ctx.reply('📸 Нужно прислать именно фото (картинкой). Попробуй еще раз.');
    }

    if (ctx.session.sender_step === 'ask_name') {
        ctx.session.sender_name = text;
        ctx.session.sender_step = 'ask_photo';
        return ctx.reply('📸 Прикрепи свое фото (картинкой или файлом).');
    }

    if (ctx.session.sender_step === 'ask_message') {
        if (text.length > 200) return ctx.reply('❌ Максимум 200 символов! Сократи текст и попробуй еще:');
        
        ctx.session.sender_text = text;
        ctx.session.sender_step = 'choose_mode';
        
        return ctx.reply(
            `📝 Послание готово: "${text}"\n\nВыбери, как его отправить:`,
            {
                parse_mode: 'HTML',
                ...Markup.inlineKeyboard([
                    [Markup.button.callback('🤫 Анонимно (автор скрыт)', 'send_anon')],
                    [Markup.button.callback('👤 Открыто (имя и фото видны)', 'send_open')]
                ])
            }
        );
    }
});

bot.action('send_anon', (ctx) => { sendMessage(ctx, false); });
bot.action('send_open', (ctx) => { sendMessage(ctx, true); });

async function sendMessage(ctx, is_open) {
    if (!ctx.session || !ctx.session.targetId) return ctx.answerCbQuery('Ошибка сессии. Начни заново.');
    
    const targetId = ctx.session.targetId;
    const text = ctx.session.sender_text;
    const sender_name = ctx.session.sender_name;
    const sender_photo = ctx.session.sender_photo;

    const msgId = addMessage(targetId, text, sender_name, sender_photo, is_open);

    const typeText = is_open ? '👤 Открыто' : '🤫 Анонимно';
    ctx.session = {};
    await ctx.reply(`✅ Послание доставлено ${typeText}!`, getMainMenu());
    
    const notifyText = is_open 
        ? '📨 <b>Тебе пришло открытое послание!</b>' 
        : '🤫 <b>Тебе пришло анонимное послание!</b>';
        
    try {
        await bot.telegram.sendMessage(targetId, notifyText, { 
            parse_mode: 'HTML', 
            ...Markup.inlineKeyboard([
                [Markup.button.callback('📬 Прочитать', `read_${msgId}`)]
            ])
        });
    } catch (e) {
        console.error(`Не удалось уведомить пользователя ${targetId}`);
    }
}

// === ЧТЕНИЕ СООБЩЕНИЙ ===
bot.action('read_messages', (ctx) => { 
    const userId = ctx.from.id.toString();
    const msgs = getUnreadMessages(userId); 
    if (msgs.length === 0) return ctx.answerCbQuery('Пусто!'); 
    ctx.session = ctx.session || {}; 
    ctx.session.msgQueue = msgs.map(m => m.id); 
    showNextMessage(ctx); 
});

bot.action(/^read_(.+)$/, (ctx) => { 
    const msgId = ctx.match[1]; 
    const msg = getMessageById(msgId); 
    if (!msg) return ctx.answerCbQuery('Сообщение не найдено (устарело)'); 
    markAsRead(msg.id); 
    showSingleMessage(ctx, msg);
});

function showNextMessage(ctx) { 
    if (!ctx.session.msgQueue || ctx.session.msgQueue.length === 0) {
        return ctx.reply('📭 Всё прочитано!', { ...getMainMenu() }); 
    }
    const msgId = ctx.session.msgQueue.shift(); 
    const msg = getMessageById(msgId); 
    if (!msg) return showNextMessage(ctx);
    markAsRead(msg.id); 
    showSingleMessage(ctx, msg);
}

function showSingleMessage(ctx, msg) {
    const userId = ctx.from.id.toString();
    if (!db.users[userId]) registerUser(userId, ctx.from.username, ctx.from.first_name);
    
    const user = db.users[userId]; 
    const isPremium = isUserPremium(user); 
    const hasAccess = msg.is_open || isPremium || msg.is_revealed;

    if (hasAccess) { 
        if (!msg.is_revealed && !msg.is_open) { revealMessage(msg.id); }
        ctx.answerCbQuery(); 
        ctx.replyWithPhoto(msg.sender_photo, { 
            caption: `📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, 
            parse_mode: 'HTML' 
        }).catch(() => {
            ctx.reply(`📩 <b>Послание:</b>\n"${msg.text}"\n\n👤 <b>Автор:</b> ${msg.sender_name}`, { parse_mode: 'HTML' });
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

// === МАГАЗИН ===
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
      `👑 <b>Премиум навсегда</b>\n\nЧто дает:\n✅ Все анонимные авторы раскрываются автоматически (без доплат)\n✅ Значок 👑 в профиле\n\nСтоимость: <b>799 ₽</b>`, 
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
        const userId = ctx.from.id.toString();
        const u = db.users[userId]; 
        u.is_premium = true; 
        u.premium_expiry = 0;
        scheduleSave(); 
        ctx.reply('👑 Премиум активирован навсегда! Все маски сняты.', {parse_mode:'HTML'}); 
    } else { 
        ctx.reply('❌ Оплата не найдена. Попробуй чуть позже или проверь, совпадает ли сумма.'); 
    } 
});

bot.action('check_reveal_0', async (ctx) => { 
    await ctx.answerCbQuery('Проверяю...'); 
    const userId = ctx.from.id.toString();
    if (await checkYooMoneyPayment(`${userId}_reveal_0`)) { 
        const m = Object.values(db.messages).find(m => m.target_id === userId && !m.is_revealed && !m.is_open);
        if(m) { 
            revealMessage(m.id); 
            ctx.replyWithPhoto(m.sender_photo, { caption: `👤 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}).catch(() => {
                ctx.reply(`👤 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, { parse_mode:'HTML' });
            });
        } else { 
            ctx.reply('🔑 Оплата прошла, но нераскрытых анонимных посланий нет!'); 
        }
    } else { 
        ctx.reply('❌ Оплата не найдена.'); 
    } 
});

bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    await ctx.answerCbQuery('Проверяю...'); 
    const userId = ctx.from.id.toString();
    if(await checkYooMoneyPayment(`${userId}_reveal_${id}`)){ 
        const m = getMessageById(id); 
        if(m) { 
            revealMessage(m.id); 
            ctx.replyWithPhoto(m.sender_photo, { caption: `👤 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, parse_mode:'HTML'}).catch(() => {
                ctx.reply(`👤 Автор раскрыт: ${m.sender_name}\n\n"${m.text}"`, { parse_mode:'HTML' });
            });
        } else {
            ctx.reply('❌ Сообщение не найдено.');
        }
    } else { 
        ctx.reply('❌ Оплата не найдена.'); 
    } 
});

// === АДМИНКА ===
bot.command('admin', async (ctx) => { 
    if (ctx.from.id.toString() !== ADMIN_ID) return; 
    ctx.session = {};
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

bot.action('admin_stats', async (ctx) => { 
    if (ctx.from.id.toString() !== ADMIN_ID) return; 
    await ctx.answerCbQuery(); 
    const u = Object.keys(db.users).length; 
    const m = Object.keys(db.messages).length; 
    ctx.reply(`📊 Статистика:\n👥 Пользователей: ${u}\n📬 Сообщений: ${m}`, {parse_mode:'HTML'}); 
});

bot.action('admin_broadcast', (ctx) => { 
    if (ctx.from.id.toString() !== ADMIN_ID) return; 
    ctx.answerCbQuery(); 
    ctx.session.waitingForBroadcast = true; 
    ctx.reply('📢 Введи текст для рассылки (HTML поддерживается):'); 
});

bot.action('admin_grant_premium', (ctx) => { 
    if (ctx.from.id.toString() !== ADMIN_ID) return; 
    ctx.answerCbQuery(); 
    ctx.session.waitingForPremiumId = true; 
    ctx.reply('👑 Введи Telegram ID пользователя:'); 
});

bot.action('admin_clear_msgs', (ctx) => { 
    if (ctx.from.id.toString() !== ADMIN_ID) return; 
    ctx.answerCbQuery(); 
    const c = Object.keys(db.messages).length; 
    db.messages = {}; 
    scheduleSave(); 
    ctx.reply(`🧹 Удалено ${c} сообщений!`); 
});

// === ЗАПУСК ===
bot.launch().then(() => console.log('🤖 Шёпот запущен!')).catch(err => console.error(err));

process.once('SIGINT', () => { bot.stop('SIGINT'); gracefulShutdown(); });
process.once('SIGTERM', () => { bot.stop('SIGTERM'); gracefulShutdown(); });
