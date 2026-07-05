const { Telegraf, Markup, Scenes, session } = require('telegraf');

// ВСТАВЬ СЮДА СВОЙ ТОКЕН ОТ BOTFATHER
const BOT_TOKEN = '8038462440:AAEoCfxTBFwfJhhDjRRJcOKhB9820rqGs6o';
const bot = new Telegraf(BOT_TOKEN);

// --- БАЗА ДАННЫХ (Временно в оперативной памяти) ---
// В продакшене используй MongoDB или PostgreSQL
const users = {}; 
const likes = {}; // Хранит кто кого лайкнул { userId: Set([targetId1, targetId2]) }

// --- ФУНКЦИИ ОФОРМЛЕНИЯ ---
function getMainKeyboard() {
  return Markup.keyboard([
    ['🔥 Лента анкет', '👤 Моя анкета'],
    ['✏️ Редактировать', '❓ Помощь']
  ]).resize();
}

function formatProfile(user) {
  return `
<b>👤 ${user.name}, ${user.age}</b>
🏙 Город: <b>${user.city}</b>

📝 О себе:
<code>${user.bio}</code>
  `;
}

// --- СЦЕНА РЕГИСТРАЦИИ ---
const registrationScene = new Scenes.WizardScene(
  'registration',
  
  // Шаг 1: Имя
  (ctx) => {
    ctx.reply('👋 Добро пожаловать в ленту знакомств!\n\nКак тебя зовут?');
    return ctx.wizard.next();
  },
  
  // Шаг 2: Возраст
  (ctx) => {
    if (!ctx.message.text) return ctx.reply('Пожалуйста, введи текст.');
    ctx.wizard.state.name = ctx.message.text;
    ctx.reply('🎂 Сколько тебе лет? (Только цифры)');
    return ctx.wizard.next();
  },
  
  // Шаг 3: Город
  (ctx) => {
    const age = parseInt(ctx.message.text);
    if (isNaN(age) || age < 14 || age > 99) {
      return ctx.reply('⚠️ Введи корректный возраст (цифрой от 14 до 99).');
    }
    ctx.wizard.state.age = age;
    ctx.reply('🏙 Из какого ты города?');
    return ctx.wizard.next();
  },
  
  // Шаг 4: О себе
  (ctx) => {
    ctx.wizard.state.city = ctx.message.text;
    ctx.reply('✍️ Расскажи немного о себе. Что любишь, чем увлекаешься?');
    return ctx.wizard.next();
  },
  
  // Шаг 5: Фото
  (ctx) => {
    ctx.wizard.state.bio = ctx.message.text;
    ctx.reply('📸 Пришли свою фотографию (именно фото, а не файл).');
    return ctx.wizard.next();
  },
  
  // Сохранение анкеты
  (ctx) => {
    if (!ctx.message.photo) {
      return ctx.reply('⚠️ Это не фотография! Пришли фото, чтобы продолжить.');
    }
    
    const photoId = ctx.message.photo[ctx.message.photo.length - 1].file_id; // Берем самое большое фото
    
    const userId = ctx.from.id.toString();
    users[userId] = {
      id: userId,
      name: ctx.wizard.state.name,
      age: ctx.wizard.state.age,
      city: ctx.wizard.state.city,
      bio: ctx.wizard.state.bio,
      photo: photoId
    };
    likes[userId] = new Set();

    ctx.replyWithPhoto(photoId, {
      caption: `✅ Твоя анкета готова!\n\n${formatProfile(users[userId])}`,
      parse_mode: 'HTML',
      ...getMainKeyboard()
    });
    
    return ctx.scene.leave();
  }
);

// Подключаем сцены и сессии
const stage = new Scenes.Stage([registrationScene]);
bot.use(session());
bot.use(stage.middleware());

// --- СТАРТ ---
bot.start(async (ctx) => {
  const userId = ctx.from.id.toString();
  if (users[userId]) {
    ctx.reply('С возвращением! 👋', getMainKeyboard());
  } else {
    ctx.scene.enter('registration');
  }
});

// --- КНОПКИ МЕНЮ ---
bot.hears('👤 Моя анкета', (ctx) => {
  const userId = ctx.from.id.toString();
  const user = users[userId];
  if (!user) return ctx.scene.enter('registration');
  
  ctx.replyWithPhoto(user.photo, {
    caption: formatProfile(user),
    parse_mode: 'HTML'
  });
});

bot.hears('✏️ Редактировать', (ctx) => {
  ctx.scene.enter('registration');
});

bot.hears('❓ Помощь', (ctx) => {
  ctx.reply(
    '<b>Как пользоваться ботом:</b>\n\n' +
    '🔥 <b>Лента анкет</b> — смотри анкеты других людей.\n' +
    '❤️ Лайк — если человек тебе понравился.\n' +
    '👎 Дизлайк — пропустить анкету.\n\n' +
    'Если вы оба нажали ❤️, это <b>взаимная симпатия</b>, и я пришлю вам контакты друг друга!',
    { parse_mode: 'HTML' }
  );
});

// --- ЛЕНТА АНКЕТ ---
bot.hears('🔥 Лента анкет', (ctx) => {
  const userId = ctx.from.id.toString();
  const user = users[userId];
  if (!user) return ctx.scene.enter('registration');

  // Ищем случайную анкету (не свою и не просмотренную)
  const allIds = Object.keys(users).filter(id => id !== userId);
  
  if (allIds.length === 0) {
    return ctx.reply('😔 Пока анкет других пользователей нет. Подожди немного!');
  }

  // Выбираем случайную анкету
  const randomId = allIds[Math.floor(Math.random() * allIds.length)];
  const targetUser = users[randomId];

  ctx.session.currentViewProfile = randomId;

  ctx.replyWithPhoto(targetUser.photo, {
    caption: formatProfile(targetUser),
    parse_mode: 'HTML',
    ...Markup.inlineKeyboard([
      [
        Markup.button.callback('❤️ Лайк', `like_${randomId}`),
        Markup.button.callback('👎 Дизлайк', 'dislike')
      ]
    ])
  });
});

// --- ОБРАБОТКА INLINE КНОПОК ---
bot.action('dislike', (ctx) => {
  ctx.answerCbQuery('Пропущено 👎');
  ctx.deleteMessage();
  // Эмулируем нажатие кнопки "Лента" для показа следующей анкеты
  ctx.reply('🔥 Лента анкет'); 
});

bot.action(/^like_(.+)$/, (ctx) => {
  const targetId = ctx.match[1]; // Кого лайкнули
  const myId = ctx.from.id.toString(); // Кто лайкнул
  
  if (!likes[myId]) likes[myId] = new Set();
  likes[myId].add(targetId);
  
  ctx.answerCbQuery('Ты поставил лайк! ❤️');
  ctx.deleteMessage();

  // ПРОВЕРКА НА ВЗАИМНОСТЬ
  if (likes[targetId] && likes[targetId].has(myId)) {
    // Взаимный лайк!
    const myProfile = users[myId];
    const targetProfile = users[targetId];

    // Оповещаем меня
    bot.telegram.sendMessage(myId, `🎉 У вас взаимная симпатия с <b>${targetProfile.name}</b>!\nВы можете написать ему/ей: @${targetProfile.id}`, { parse_mode: 'HTML' }); // В реальном боте тут username
    
    // Оповещаем цель
    bot.telegram.sendMessage(targetId, `🎉 У вас взаимная симпатия с <b>${myProfile.name}</b>!\nВы можете написать ему/ей: @${myProfile.id}`, { parse_mode: 'HTML' });
  }

  // Показываем следующую анкету
  ctx.reply('🔥 Лента анкет');
});

// --- ЗАПУСК БОТА ---
bot.launch().then(() => {
  console.log('🚀 Бот для знакомств успешно запущен!');
}).catch((err) => {
  console.error('Ошибка запуска:', err);
});

// Безопасное отключение
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
