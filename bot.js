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
            last_spin_time: 0, free_keys: 0, ref_count: 0, msg_count: 0, reputation_title: "Гость", referred_by: null
        }; 
        scheduleSave(); 
    }
}

function addMessage(target_id, text, sender_name, sender_photo) { 
    const id = Date.now(); 
    // Убрали ауру, добавили is_read
    db.messages[id] = { id, target_id, text, sender_name, sender_photo, is_read: false, reveal_bought: false }; 
    scheduleSave(); return id; 
}

function getUnreadMessages(target_id) { return Object.values(db.messages).filter(m => m.target_id === target_id && !m.is_read).sort((a, b) => b.id - a.id); }
function getMessageById(id) { return db.messages[id]; }
function markAsRead(id) { const m = db.messages[id]; if (m) { m.is_read = true; scheduleSave(); } }

// === УТИЛИТЫ ===
function updateReputation(user) {
    if (user.msg_count >= 20) user.reputation_title = "🎭 Магистр Маскарада";
    else if (user.msg_count >= 10) user.reputation_title = "💀 Лорд Тайн";
    else if (user.msg_count >= 5) user.reputation_title = "👁 Искатель";
    else user.reputation_title = "🌑 Гость";
    scheduleSave();
}

function getMainMenu() { 
    return Markup.keyboard([
        ['📨 Послания', '🎭 Снять маску'], 
        ['🎡 Фортуна', '👤 Профиль']
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
  registerUser(userId, ctx.from.username || 'no_user', ctx.from.first_name || 'Странник');
  const payload = ctx.startPayload;

  // Рефералка
  if (payload && payload.startsWith('r_')) {
    const refId = parseInt(payload.replace('r_', ''));
    if (refId !== userId && db.users[refId]) {
        if (!db.users[userId].referred_by) {
            db.users[userId].referred_by = refId;
            db.users[refId].ref_count++;
            if (db.users[refId].ref_count % 3 === 0) {
                db.users[refId].free_keys++;
                bot.telegram.sendMessage(refId, '🎉 Твой друг перешел по ссылке! Ты получил 1 Ключ Маскарада!').catch(()=>{});
            } else {
                bot.telegram.sendMessage(refId, '👥 Новый друг на балу! Осталось ' + (3 - (db.users[refId].ref_count % 3)) + ' чел. для Ключа.').catch(()=>{});
            }
            scheduleSave();
        }
    }
    return ctx.reply('🎭 Добро пожаловать! Твой друг пригласил тебя на бал Маскарада.', { parse_mode: 'HTML', ...getMainMenu() });
  }

  // Отправка сообщения
  if (payload && payload.startsWith('w_')) {
    const targetId = parseInt(payload.replace('w_', ''));
    const targetUser = db.users[targetId];
    if (!targetUser) return ctx.reply('Этот человек еще не на балу :(');
    
    ctx.session = { targetId: targetId, sender_step: 'ask_name' };
    return ctx.reply(
      `🎭 <b>Оставь послание для ${targetUser.first_name}</b>\n\nНапиши свое имя и фото. Получатель прочитает текст бесплатно, но твое лицо будет скрыто за маской!\n\n👤 Твое имя:`,
      { parse_mode: 'HTML', reply_markup: Markup.removeKeyboard() }
    );
  }

  // Обычный вход
  ctx.session = {};
  const user = db.users[userId];
  const badge = user.is_premium ? '👑' : (user.is_vip ? '💎' : '');
  
  await ctx.reply(
    `👋 <b>Добро пожаловать на бал, ${badge} ${user.first_name}!</b>\n\n` +
    `Это Шёпот — здесь люди пишут тебе тайные послания.\n\n` +
    `📩 Тексты ты читаешь <b>бесплатно</b>.\n` +
    `🎭 Но все отправители скрыты масками. Кто-то из них — твой тайный поклонник!\n` +
    `🔑 Используй <b>Ключ Маскарада</b>, чтобы снять маску и увидеть лицо автора.\n\n` +
    `🔑 Твоих ключей: <b>${user.free_keys}</b>`,
    { parse_mode: 'HTML', ...getMainMenu() }
  );
});

// --- КНОПКИ МЕНЮ ---
bot.hears('📨 Послания', (ctx) => {
  const msgs = getUnreadMessages(ctx.from.id);
  if (msgs.length === 0) return ctx.reply('📭 Пока пусто. Поделись ссылкой, чтобы получать послания!');
  ctx.session = ctx.session || {};
  ctx.session.msgQueue = msgs.map(m => m.id);
  showNextMessage(ctx);
});

bot.hears('🎭 Снять маску', (ctx) => {
  const user = db.users[ctx.from.id];
  const hasKeys = user.free_keys > 0 || (user.is_vip && user.reveal_credits > 0) || (user.is_premium && user.premium_expiry > Date.now());
  
  if (hasKeys) {
    ctx.reply('🎭 У тебя есть Ключи! Нажми кнопку "🎭 Снять маску" под любым посланием, которое читаешь, чтобы увидеть автора.', { parse_mode: 'HTML' });
  } else {
    ctx.reply(
      `🎭 <b>У тебя 0 Ключей Маскарада</b>\n\nЧтобы узнать, кто скрывается за маской, нужны ключи. Их можно получить так:\n\n🎡 Крутить колесо Фортуны (бесплатно раз в сутки)\n👥 Пригласить 3 друзей по ссылке в Профиле\n💰 Купить в Магазине`,
      { parse_mode: 'HTML' }
    );
  }
});

bot.hears('🎡 Фортуна', (ctx) => {
  const user = db.users[ctx.from.id];
  const now = Date.now();
  const hours24 = 24 * 60 * 60 * 1000;

  if (now - user.last_spin_time < hours24) {
    const timeLeft = Math.ceil((hours24 - (now - user.last_spin_time)) / (60 * 60 * 1000));
    return ctx.reply(`⏳ Колесо отдыхает.\n\nСледующий спин через <b>${timeLeft} ч.</b>`, { parse_mode: 'HTML' });
  }

  ctx.reply('🎡 <b>Колесо Фортуны!</b>\n\nКрути раз в сутки! Выпадут ключи или аура.', {
    parse_mode: 'HTML',
    ...Markup.inlineKeyboard([
      [Markup.button.callback('🎡 Крутить!', 'spin_wheel')]
    ])
  });
});

bot.hears('👤 Профиль', (ctx) => {
  const user = db.users[userId];
  const link = `https://t.me/${ctx.botInfo.username}?start=r_${ctx.from.id}`;
  ctx.reply(
    `👤 <b>Твой профиль</b>\n\n` +
    `🎭 Репутация: <b>${user.reputation_title}</b>\n` +
    `📩 Получено посланий: <b>${user.msg_count}</b>\n` +
    `🔑 Ключей Маскарада: <b>${user.free_keys}</b>\n` +
    `👥 Друзей приглашено: <b>${user.ref_count}</b>\n\n` +
    `🔗 <b>Твоя ссылка:</b>\n<code>${link}</code>\n<i>Каждые 3 друга = 1 бесплатный Ключ!</i>`,
    { parse_mode: 'HTML' }
  );
});

bot.hears('💰 Магазин', (ctx) => {
  ctx.reply(
    `💰 <b>Магазин Маскарада</b>\n\nВыбери, что тебе нужно:`,
    { 
      parse_mode: 'HTML', 
      ...Markup.inlineKeyboard([
        [Markup.button.callback('🔑 Ключ Маскарада (149 ₽)', 'shop_reveal')],
        [Markup.button.callback('💎 VIP Статус (399 ₽)', 'shop_vip')],
        [Markup.button.callback('👑 PREMIUM Статус (799 ₽)', 'shop_premium')]
      ])
    }
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
  
  // Админ-логика
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
    return ctx.reply('📸 Прикрепи фото (картинкой). Оно будет скрыто за маской!');
  }

  if (ctx.session.sender_step === 'ask_message') {
    const targetId = ctx.session.targetId;
    if (text.length > 200) return ctx.reply('Максимум 200!');
    const msgId = addMessage(targetId, text, ctx.session.sender_name, ctx.session.sender_photo);
    
    db.users[targetId].msg_count++;
    updateReputation(db.users[targetId]);

    ctx.session = {};
    await ctx.reply('✅ Тайна доставлена! Маска на месте 🎭', getMainMenu());
    try {
      await bot.telegram.sendMessage(targetId, '🤫 <b>Тебе пришло новое послание от тайного гостя!</b>', { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.callback('📨 Прочитать', `read_${msgId}`)]
        ])
      });
    } catch (e) {}
  }
});

// === ЧТЕНИЕ СООБЩЕНИЙ (Текст БЕСПЛАТНО, Маска ПЛАТНО) ===
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
  const isVip = user.is_vip && user.vip_expiry > Date.now(); 
  const isPremium = user.is_premium && user.premium_expiry > Date.now(); 
  const hasAccess = isPremium || (isVip && user.reveal_credits > 0) || msg.reveal_bought || user.free_keys > 0;

  if (hasAccess) { 
    if (isVip && !isPremium) { user.reveal_credits--; } 
    else if (!msg.reveal_bought && !isPremium) { user.free_keys--; } 
    scheduleSave(); 
    ctx.answerCbQuery(); 
    ctx.replyWithPhoto(msg.sender_photo, { 
      caption: `📩 <b>Послание:</b>\n"${msg.text}"\n\n🎭 <b>Маска снята! Это:</b> ${msg.sender_name}`, 
      parse_mode: 'HTML' 
    }); 
  } else { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `📩 <b>Послание:</b>\n"${msg.text}"\n\n🎭 <i>Отправитель скрыт за маской. Хочешь узнать, кто этот тайный гость и увидеть фото?</i>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.callback('🎭 Снять маску (1 Ключ)', `use_key_${msg.id}`)],
          [Markup.button.callback('🔑 Купить ключи', `buy_reveal_${msg.id}`), Markup.button.callback('➡️ Далее', 'skip_msg')]
        ]) 
      }
    ); 
  }
}

bot.action('skip_msg', (ctx) => { ctx.answerCbQuery(); showNextMessage(ctx); });

// === ИСПОЛЬЗОВАНИЕ КЛЮЧЕЙ ===
bot.action(/^use_key_(.+)$/, (ctx) => { 
  const id = ctx.match[1]; 
  const user = db.users[ctx.from.id]; 
  if (user.free_keys <= 0) return ctx.answerCbQuery('У тебя 0 ключей! Купи в Магазине.'); 
  const m = getMessageById(parseInt(id)); 
  if(!m) return ctx.answerCbQuery('Ошибка'); 
  user.free_keys--; 
  m.reveal_bought = true; 
  scheduleSave(); 
  ctx.answerCbQuery(); 
  ctx.replyWithPhoto(m.sender_photo, { caption: `🎭 <b>Маска снята! Это:</b> ${m.sender_name}\n\n"${m.text}"`, parse_mode: 'HTML' }); 
});

// === КОЛЕСО ФОРТУНЫ ===
bot.action('spin_wheel', (ctx) => { 
  const user = db.users[ctx.from.id]; 
  const now = Date.now(); 
  if (now - user.last_spin_time < 24*60*60*1000) return ctx.answerCbQuery('Рано! Приходи завтра.'); 
  user.last_spin_time = now; 
  const rand = Math.random(); 
  let prize = ''; 
  if (rand < 0.25) { user.free_keys++; prize = '🔑 Ты выиграл 1 Ключ Маскарада!'; } 
  else if (rand < 0.60) { user.msg_count += 3; updateReputation(user); prize = '✨ Твоя репутация выросла!'; } 
  else { user.msg_count += 1; updateReputation(user); prize = '🌙 Твоя репутация немного выросла'; } 
  scheduleSave(); 
  ctx.answerCbQuery(); 
  ctx.reply(
    `🎡 <b>Колесо Фортуны!</b>\n\n${prize}\n🎭 Репутация: <b>${user.reputation_title}</b>\n🔑 Ключей: ${user.free_keys}`, 
    { parse_mode: 'HTML' }
  ); 
});

// === МАГАЗИН (ПОДРОБНОЕ ОПИСАНИЕ) ===
bot.action('shop_reveal', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `🔑 <b>Ключ Маскарада</b>\n\nЧто дает: Снимает маску с ОДНОГО тайного гостя. Ты увидишь его настоящее фото и узнаешь имя.\n\nСтоимость: <b>149 ₽</b>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.url('💳 Оплатить', generatePaymentLink(149, `${ctx.from.id}_reveal_0`))], 
          [Markup.button.callback('✅ Я оплатил', 'check_reveal_0')]
        ]) 
      }
    ); 
});

bot.action('shop_vip', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `💎 <b>VIP Статус (1 месяц)</b>\n\nЧто дает:\n✅ 5 Ключей Маскарада сразу\n✅ Значок 💎 в профиле\n\nСтоимость: <b>399 ₽</b>`, 
      { 
        parse_mode: 'HTML', 
        ...Markup.inlineKeyboard([
          [Markup.button.url('💳 Оплатить', generatePaymentLink(399, `${ctx.from.id}_vip`))], 
          [Markup.button.callback('✅ Я оплатил', 'check_vip')]
        ]) 
      }
    ); 
});

bot.action('shop_premium', (ctx) => { 
    ctx.answerCbQuery(); 
    ctx.reply(
      `👑 <b>PREMIUM Статус (1 месяц)</b>\n\nЧто дает:\n✅ Маски снимаются автоматически (без ключей)\n✅ 2 бесплатных Ключа каждый день от Фортуны\n✅ Значок 👑 в профиле\n\nСтоимость: <b>799 ₽</b>`, 
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
      `🔑 Купить Ключ Маскарада (149₽)`, 
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
bot.action('check_vip', async (ctx) => { 
    await ctx.answerCbQuery('Проверка...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_vip`)) { 
        const u=db.users[ctx.from.id]; u.is_vip=true; u.vip_expiry=Date.now()+30*24*60*60*1000; u.reveal_credits+=5; scheduleSave(); ctx.reply('💎 VIP! 5 ключей добавлено.', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Не найдено'); } 
});

bot.action('check_premium', async (ctx) => { 
    await ctx.answerCbQuery('Проверка...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_premium`)) { 
        const u=db.users[ctx.from.id]; u.is_premium=true; u.premium_expiry=Date.now()+30*24*60*60*1000; scheduleSave(); ctx.reply('👑 PREMIUM! Все маски открыты!', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Не найдено'); } 
});

bot.action('check_reveal_0', async (ctx) => { 
    await ctx.answerCbQuery('Проверка...'); 
    if (await checkYooMoneyPayment(`${ctx.from.id}_reveal_0`)) { 
        const u=db.users[ctx.from.id]; u.free_keys++; scheduleSave(); ctx.reply('🔑 Ключ куплен! Используй его под посланием.', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Не найдено'); } 
});

bot.action(/^check_reveal_specific_(.+)$/, async (ctx) => { 
    const id = ctx.match[1]; 
    await ctx.answerCbQuery('Проверка...'); 
    if(await checkYooMoneyPayment(`${ctx.from.id}_reveal_${id}`)){ 
        const u=db.users[ctx.from.id]; u.free_keys++; scheduleSave(); ctx.reply('🔑 Ключ куплен!', {parse_mode:'HTML'}); 
    } else { ctx.reply('❌ Не найдено'); } 
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

bot.action('admin_stats', async (ctx) => { if (ctx.from.id !== ADMIN_ID) return; await ctx.answerCbQuery(); const u=Object.keys(db.users).length; const m=Object.keys(db.messages).length; const p=Object.values(db.users).filter(u=>u.is_premium&&u.premium_expiry>Date.now()).length; ctx.reply(`📊:\n👥 ${u}\n👑 ${p}\n📬 ${m}`, {parse_mode:'HTML'}); });
bot.action('admin_broadcast', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); adminState.waitingForBroadcast=true; ctx.reply('📢 Текст:'); });
bot.action('admin_grant_premium', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); adminState.waitingForPremiumId=true; ctx.reply('👑 ID:'); });
bot.action('admin_clear_msgs', (ctx) => { if (ctx.from.id !== ADMIN_ID) return; ctx.answerCbQuery(); const c=Object.keys(db.messages).length; db.messages={}; scheduleSave(); ctx.reply(`🧹 ${c}!`); });

bot.launch().then(() => console.log('🤖 Маскарад запущен!')).catch(err => console.error(err));
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
