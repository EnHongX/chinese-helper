(function () {
  const form = document.querySelector("#character-form");
  const input = document.querySelector("#character-input");
  const clearInputButton = document.querySelector("#clear-input-button");
  const cards = document.querySelector("#cards");
  const summary = document.querySelector("#result-summary");
  const resultsTitle = document.querySelector("#results-title");
  const searchTitle = document.querySelector("#search-title");
  const searchDescription = document.querySelector("#search-description");
  const searchPanel = document.querySelector(".search-panel");
  const printButton = document.querySelector("#print-button");
  const navItems = document.querySelectorAll(".nav-item");
  const template = document.querySelector("#character-card-template");
  const simpleTemplate = document.querySelector("#simple-card-template");

  const pager = document.querySelector("#char-pager");
  const pagerPages = document.querySelector("#pager-pages");
  const pagerCounter = document.querySelector("#pager-counter");
  const prevBtn = pager.querySelector(".pager-nav.prev");
  const nextBtn = pager.querySelector(".pager-nav.next");

  const defaultCharacters = ["小", "学", "语", "文"];
  let currentFeature = "hanzi";
  let historyItems = [];
  let currentCharacters = [];
  let currentCharIndex = 0;

  // Dictation state
  let dictationPool = [];
  let dictationSelected = [];
  let dictationSession = null; // { characters, total_count, current_index, results }
  let dictationCurrentAnswer = ""; // correct char for current question
  let dictationWrongAttempts = 0;
  let dictationSubmitting = false;
  let dictationManualChars = [];
  let dictationCurrentState = null; // {position, wrongAttempts, lastAnswer, isCorrect}
  let dictationHistoryItems = [];

  const speechSupported = typeof window !== "undefined" && "speechSynthesis" in window;
  let chineseVoice = null;
  let lastSpeakError = null;

  function loadChineseVoice() {
    if (!speechSupported) return;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return;
    const exact = voices.find((v) => v.lang === "zh-CN" || v.lang === "zh_CN");
    const broad = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("zh"));
    chineseVoice = exact || broad || null;
    console.info(
      "[speech] voices loaded:",
      voices.length,
      "| chineseVoice:",
      chineseVoice ? `${chineseVoice.name} (${chineseVoice.lang})` : "未找到中文 voice"
    );
  }

  if (speechSupported) {
    loadChineseVoice();
    window.speechSynthesis.addEventListener("voiceschanged", loadChineseVoice);
    // 暴露调试入口
    window.__speechDebug = {
      listVoices: () => window.speechSynthesis.getVoices(),
      current: () => chineseVoice,
      test: (text) => speakText(text || "小学语文")
    };
  } else {
    console.warn("[speech] 当前浏览器不支持 speechSynthesis");
  }

  function buildUtterance(text, options) {
    const utter = new SpeechSynthesisUtterance(text);
    if (chineseVoice) utter.voice = chineseVoice;
    utter.lang = "zh-CN";
    utter.rate = options.rate != null ? options.rate : 0.8;
    utter.pitch = options.pitch != null ? options.pitch : 1.05;
    utter.volume = options.volume != null ? options.volume : 1;
    utter.onstart = (event) => {
      console.info("[speech] onstart:", text);
      if (options.onstart) options.onstart(event);
    };
    utter.onend = (event) => {
      console.info("[speech] onend:", text);
      if (options.onend) options.onend(event);
    };
    utter.onerror = (event) => {
      lastSpeakError = event && event.error;
      console.warn("[speech] onerror:", event && event.error, "text:", text);
      if (options.onerror) options.onerror(event);
    };
    return utter;
  }

  function speakText(text, opts) {
    if (!speechSupported || !text) return null;
    const options = opts || {};
    if (!chineseVoice) loadChineseVoice();

    const utter = buildUtterance(String(text).trim(), options);
    const isBusy = window.speechSynthesis.speaking || window.speechSynthesis.pending;
    if (isBusy) {
      window.speechSynthesis.cancel();
      setTimeout(() => window.speechSynthesis.speak(utter), 80);
    } else {
      window.speechSynthesis.speak(utter);
    }
    console.info(
      "[speech] speak() called:",
      text,
      "| voice:",
      chineseVoice ? chineseVoice.name : "(浏览器默认)",
      "| total voices:",
      window.speechSynthesis.getVoices().length
    );
    return utter;
  }

  const unsafeWordPattern = /[亵侮妓娼嫖赌毒尸屎尿淫奸杀凶狱刑殡丧]/u;
  const SHARD_BUCKETS = 32;
  const shardCache = new Map();
  const shardPromises = new Map();

  const featureCopy = {
    hanzi: {
      title: "输入要学习的汉字",
      description: "可以输入一个或多个汉字，系统会逐个展示字形、拼音、笔画和组词。",
      placeholder: "例如：小学语文",
      help: "非汉字内容会自动忽略。数据不足的字段会显示“暂无”。",
      resultsTitle: "学习卡片"
    },
    meaning: {
      title: "输入汉字或词语",
      description: "用顿号分割多个内容，例如：大、小 或 高山、辛苦、努力。",
      placeholder: "例如：高山、辛苦、努力",
      help: "按“、”分割后，分别输出近义词和反义词。",
      resultsTitle: "字义辨析"
    },
    words: {
      title: "输入要组词的汉字",
      description: "用顿号分割多个汉字，例如：大、小。每个字输出 5 个常见组词。",
      placeholder: "例如：大、小",
      help: "优先展示内置数据；数据不足时显示“暂无”。",
      resultsTitle: "组词练习"
    },
    sentences: {
      title: "输入要造句的字或词",
      description: "用顿号分割多个字词，例如：小、努力。每个字词输出 3 条句子。",
      placeholder: "例如：小、努力",
      help: "单字优先使用分级造句，词语使用内置例句。",
      resultsTitle: "造句练习"
    },
    history: {
      title: "学习记录",
      description: "查看本地查询历史，可单选或多选删除记录。",
      placeholder: "",
      help: "点击记录内容会自动切换到对应功能并回填查询。",
      resultsTitle: "学习记录"
    },
    dictation: {
      title: "听写练习",
      description: "从查过的字里选，或自己输入要听写的汉字。",
      placeholder: "",
      help: "一次最少 2 个字、最多 20 个字，重复字只算一个。",
      resultsTitle: "听写练习"
    }
  };

  const featureLabels = {
    hanzi: "汉字",
    meaning: "字义",
    words: "组词",
    sentences: "造句",
    history: "记录",
    dictation: "听写"
  };

  const phraseData = new Map([
    [
      "高山",
      {
        synonyms: ["高峰", "大山"],
        antonyms: ["平地", "低谷"],
        sentences: ["远处的高山像绿色的屏障。", "我们站在高山脚下仰望山顶。", "高山上的风很大，大家要注意安全。"]
      }
    ],
    [
      "辛苦",
      {
        synonyms: ["劳累", "辛劳", "吃力"],
        antonyms: ["轻松", "舒服"],
        sentences: ["妈妈工作很辛苦。", "虽然训练很辛苦，但大家都没有放弃。", "农民伯伯辛苦劳动，换来了丰收的粮食。"]
      }
    ],
    [
      "努力",
      {
        synonyms: ["勤奋", "用功", "尽力"],
        antonyms: ["懒惰", "松懈"],
        sentences: ["我要努力学习。", "只要持续努力，就会一点点进步。", "面对困难时，他没有退缩，而是更加努力地寻找办法。"]
      }
    ]
  ]);

  function isChineseCharacter(char) {
    return /\p{Script=Han}/u.test(char);
  }

  function uniqueChineseCharacters(value) {
    const seen = new Set();
    return Array.from(value).filter((char) => {
      if (!isChineseCharacter(char) || seen.has(char)) {
        return false;
      }
      seen.add(char);
      return true;
    });
  }

  function splitTerms(value) {
    const terms = value
      .split(/[、，,\s]+/u)
      .map((term) => term.trim())
      .filter(Boolean)
      .map((term) => Array.from(term).filter(isChineseCharacter).join(""))
      .filter(Boolean);

    return Array.from(new Set(terms));
  }

  function shardKey(char) {
    return (char.codePointAt(0) % SHARD_BUCKETS).toString(16).padStart(2, "0");
  }

  function loadShard(key) {
    if (shardCache.has(key)) {
      return Promise.resolve(shardCache.get(key));
    }
    if (shardPromises.has(key)) {
      return shardPromises.get(key);
    }
    const promise = fetch(`./data/generated/chars/${key}.json`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        const value = payload || { characters: {}, commonWords: {} };
        shardCache.set(key, value);
        return value;
      })
      .catch(() => {
        const value = { characters: {}, commonWords: {} };
        shardCache.set(key, value);
        return value;
      });
    shardPromises.set(key, promise);
    return promise;
  }

  function ensureShardsForChars(chars) {
    const keys = new Set();
    for (const char of chars) {
      if (isChineseCharacter(char)) {
        keys.add(shardKey(char));
      }
    }
    if (!keys.size) {
      return Promise.resolve();
    }
    return Promise.all(Array.from(keys, loadShard));
  }

  function ensureShardsForTerms(terms) {
    const all = [];
    for (const term of terms) {
      for (const ch of term) {
        all.push(ch);
      }
    }
    return ensureShardsForChars(all);
  }

  function shardChar(character) {
    const shard = shardCache.get(shardKey(character));
    return shard ? shard.characters[character] || null : null;
  }

  function shardWords(character) {
    const shard = shardCache.get(shardKey(character));
    return shard ? shard.commonWords[character] || [] : [];
  }

  function commonWordsFor(character) {
    return shardWords(character)
      .filter((word) => !unsafeWordPattern.test(word))
      .slice(0, 5);
  }

  function valueOrEmpty(value) {
    if (Array.isArray(value)) {
      return value.length ? value.join("；") : "暂无";
    }
    return value || "暂无";
  }

  function fallbackRecord(character) {
    const generated = shardChar(character) || {};
    return {
      character,
      pinyin: generated.pinyin || "暂无",
      tone: generated.tone || "暂无",
      initial: generated.initial || "暂无",
      final: generated.final || "暂无",
      syllableType: generated.syllableType || "暂无",
      strokes: [],
      strokeCount: generated.strokeCount || "",
      words: commonWordsFor(character),
      polyphonic: [],
      radical: generated.radical || "暂无",
      structure: "暂无",
      meaning: generated.meaning || "暂无",
      antonyms: [],
      synonyms: [],
      sentences: {},
      measureWords: []
    };
  }

  function mergeFallback(record) {
    const generated = shardChar(record.character) || {};
    return {
      ...record,
      pinyin: record.pinyin || generated.pinyin || "暂无",
      tone: record.tone || generated.tone || "暂无",
      initial: record.initial || generated.initial || "暂无",
      final: record.final || generated.final || "暂无",
      syllableType: record.syllableType || generated.syllableType || "暂无",
      radical: record.radical || generated.radical || "暂无",
      strokeCount: record.strokeCount || generated.strokeCount || "",
      meaning: record.meaning || generated.meaning || "暂无",
      words:
        Array.isArray(record.words) && record.words.length
          ? record.words
          : commonWordsFor(record.character)
    };
  }

  function getEntry(term) {
    if (phraseData.has(term)) {
      return phraseData.get(term);
    }
    if (term.length === 1 && shardChar(term)) {
      return fallbackRecord(term);
    }
    return null;
  }

  function makeChipSpeakable(li, text) {
    if (!speechSupported || !text) return;
    li.classList.add("speakable-chip");
    li.setAttribute("role", "button");
    li.setAttribute("tabindex", "0");
    li.setAttribute("aria-label", `朗读：${text}`);

    const icon = document.createElement("span");
    icon.className = "chip-speak-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "🔊";
    li.append(icon);

    const handler = () => {
      if (li.classList.contains("is-speaking")) return;
      speakText(text, {
        rate: 0.8,
        onstart: () => li.classList.add("is-speaking"),
        onend: () => li.classList.remove("is-speaking"),
        onerror: () => li.classList.remove("is-speaking")
      });
    };

    li.addEventListener("click", handler);
    li.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handler();
      }
    });
  }

  function renderList(listElement, values, emptyText, className, speakable) {
    listElement.innerHTML = "";
    const hasValues = Array.isArray(values) && values.length > 0;
    const items = hasValues ? values : [emptyText];

    items.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      if (hasValues && className) {
        item.className = className;
      }
      if (hasValues && speakable) {
        makeChipSpeakable(item, value);
      }
      listElement.append(item);
    });
  }

  function strokeText(strokes) {
    if (!Array.isArray(strokes) || !strokes.length) {
      return "暂无笔画数据";
    }

    const detail = strokes
      .map((stroke) => {
        if (typeof stroke === "string") {
          return stroke;
        }
        return stroke.mark ? `${stroke.name}（${stroke.mark}）` : stroke.name;
      })
      .join("、");

    return `${detail}，共${strokes.length}画`;
  }

  function strokeSummary(record) {
    if (Array.isArray(record.strokes) && record.strokes.length) {
      return strokeText(record.strokes);
    }
    if (record.strokeCount) {
      return `文本笔画名称暂未收录，可点击上方“笔顺动画”查看写法；已知共${record.strokeCount}画`;
    }
    return "文本笔画名称暂未收录，可点击上方“笔顺动画”查看写法";
  }

  function buildSentenceRow(label, text) {
    const row = document.createElement("p");
    row.className = "sentence-row";

    const badge = document.createElement("strong");
    badge.textContent = label;

    const body = document.createElement("span");
    body.className = "sentence-text";
    body.textContent = text || "暂无";

    row.append(badge, body);

    if (speechSupported && text && text !== "暂无") {
      const speakBtn = document.createElement("button");
      speakBtn.type = "button";
      speakBtn.className = "sentence-speak-btn";
      speakBtn.setAttribute("aria-label", `朗读句子：${text}`);
      speakBtn.innerHTML = '<span aria-hidden="true">🔊</span>';
      speakBtn.addEventListener("click", () => {
        if (speakBtn.disabled) return;
        speakText(text, {
          rate: 0.85,
          onstart: () => {
            speakBtn.classList.add("is-speaking");
            speakBtn.disabled = true;
          },
          onend: () => {
            speakBtn.classList.remove("is-speaking");
            speakBtn.disabled = false;
          },
          onerror: () => {
            speakBtn.classList.remove("is-speaking");
            speakBtn.disabled = false;
          }
        });
      });
      row.append(speakBtn);
    }

    return row;
  }

  function renderSentences(container, sentences) {
    container.innerHTML = "";
    const items = [
      ["初级", sentences && sentences.beginner],
      ["中级", sentences && sentences.intermediate],
      ["高级", sentences && sentences.advanced]
    ];

    items.forEach(([label, text]) => {
      container.append(buildSentenceRow(label, text));
    });
  }

  function setupStrokeControls(node, character) {
    const grid = node.querySelector(".tian-grid");
    const bigChar = grid.querySelector(".big-character");
    const mount = grid.querySelector(".writer-mount");
    const controls = node.querySelector(".stroke-controls");
    const animateBtn = controls.querySelector('[data-action="animate"]');
    const quizBtn = controls.querySelector('[data-action="quiz"]');
    const resetBtn = controls.querySelector('[data-action="reset"]');

    if (!window.HanziWriter) {
      controls.hidden = true;
      return;
    }

    let writer = null;

    function resetMount() {
      mount.innerHTML = "";
      mount.hidden = true;
      bigChar.hidden = false;
      resetBtn.hidden = true;
      writer = null;
    }

    function createWriter(options) {
      mount.innerHTML = "";
      mount.hidden = false;
      bigChar.hidden = true;
      resetBtn.hidden = false;
      const gridSize = Math.round(Math.min(grid.clientWidth, grid.clientHeight)) || 280;

      writer = window.HanziWriter.create(mount, character, Object.assign({
        width: gridSize,
        height: gridSize,
        padding: Math.max(12, Math.round(gridSize * 0.06)),
        showCharacter: false,
        showOutline: true,
        strokeAnimationSpeed: 1,
        delayBetweenStrokes: 220,
        strokeColor: "#1f1f1f",
        outlineColor: "#dccab2",
        radicalColor: "#a8321d",
        onLoadCharDataError: () => {
          resetMount();
          [animateBtn, quizBtn].forEach((btn) => {
            btn.disabled = true;
            btn.textContent = btn === animateBtn ? "无笔顺数据" : "无笔顺数据";
          });
        }
      }, options));
      return writer;
    }

    function playReward(text) {
      const reward = node.querySelector(".reward-burst");
      if (!reward) return;
      reward.textContent = text;
      reward.classList.remove("show");
      void reward.offsetWidth;
      reward.classList.add("show");
    }

    animateBtn.addEventListener("click", () => {
      const w = createWriter({ showCharacter: false });
      w.animateCharacter({
        onComplete: () => playReward("✨ 学到啦！")
      });
    });

    quizBtn.addEventListener("click", () => {
      createWriter({
        showCharacter: false,
        showOutline: true,
        showHintAfterMisses: 2
      }).quiz({
        onComplete: () => playReward("👍 真棒！")
      });
    });

    resetBtn.addEventListener("click", resetMount);
  }

  function setupTabSwitching(node) {
    const tabs = Array.from(node.querySelectorAll(".card-tab"));
    const panels = Array.from(node.querySelectorAll(".card-panel"));

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const target = tab.dataset.tab;
        tabs.forEach((t) => {
          const active = t.dataset.tab === target;
          t.classList.toggle("is-active", active);
          t.setAttribute("aria-selected", active ? "true" : "false");
        });
        panels.forEach((p) => {
          const active = p.dataset.panel === target;
          p.hidden = !active;
          p.classList.toggle("is-active", active);
        });
      });
    });
  }

  function renderCard(record) {
    const node = template.content.firstElementChild.cloneNode(true);
    const character = record.character;

    node.querySelector(".big-character").textContent = character;
    node.querySelector(".character-label").textContent = `汉字：${character}`;

    const pinyinBig = node.querySelector('[data-field="pinyin-big"]');
    const pinyinValue = record.pinyin && record.pinyin !== "暂无" ? record.pinyin : "—";
    pinyinBig.textContent = pinyinValue;

    node.querySelector('[data-field="pinyin"]').textContent = valueOrEmpty(record.pinyin);
    node.querySelector('[data-field="tone"]').textContent = valueOrEmpty(record.tone);
    node.querySelector('[data-field="initial"]').textContent = valueOrEmpty(record.initial);
    node.querySelector('[data-field="final"]').textContent = valueOrEmpty(record.final);
    node.querySelector('[data-field="syllableType"]').textContent = valueOrEmpty(record.syllableType);
    node.querySelector('[data-field="polyphonic"]').textContent = valueOrEmpty(record.polyphonic);
    node.querySelector('[data-field="radical"]').textContent = valueOrEmpty(record.radical);
    node.querySelector('[data-field="structure"]').textContent = valueOrEmpty(record.structure);
    node.querySelector('[data-field="meaning"]').textContent = valueOrEmpty(record.meaning);
    node.querySelector('[data-field="synonyms"]').textContent = valueOrEmpty(record.synonyms);
    node.querySelector('[data-field="antonyms"]').textContent = valueOrEmpty(record.antonyms);

    node.querySelector(".stroke-summary").textContent = strokeSummary(record);
    renderList(node.querySelector(".word-list"), record.words, "暂无组词数据", "word-chip", true);
    renderSentences(node.querySelector(".sentence-list"), record.sentences);
    renderList(node.querySelector(".measure-list"), record.measureWords, "暂无量词搭配", "measure-chip", true);

    setupTabSwitching(node);
    setupStrokeControls(node, character);
    setupSpeak(node, character);

    return node;
  }

  function setupSpeak(node, character) {
    const btn = node.querySelector('[data-action="speak"]');
    if (!btn) return;

    if (!speechSupported) {
      btn.disabled = true;
      btn.title = "当前浏览器不支持语音朗读";
      return;
    }

    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      speakText(character, {
        rate: 0.75,
        onstart: () => {
          btn.classList.add("is-speaking");
          btn.disabled = true;
        },
        onend: () => {
          btn.classList.remove("is-speaking");
          btn.disabled = false;
        },
        onerror: () => {
          btn.classList.remove("is-speaking");
          btn.disabled = false;
        }
      });
    });
  }

  function showLoading() {
    cards.innerHTML = "";
    const loading = document.createElement("div");
    loading.className = "loading-state";
    loading.textContent = "正在加载字典…";
    cards.append(loading);
  }

  function hidePager() {
    pager.hidden = true;
    pagerPages.innerHTML = "";
  }

  function renderPager() {
    if (currentCharacters.length <= 1) {
      hidePager();
      return;
    }
    pager.hidden = false;
    pagerPages.innerHTML = "";
    currentCharacters.forEach((char, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pager-page" + (idx === currentCharIndex ? " is-active" : "");
      btn.textContent = char;
      btn.dataset.index = String(idx);
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-label", `第 ${idx + 1} 个字：${char}`);
      btn.setAttribute("aria-selected", idx === currentCharIndex ? "true" : "false");
      btn.addEventListener("click", () => goToCharIndex(idx));
      pagerPages.append(btn);
    });
    updatePagerNav();
  }

  function updatePagerNav() {
    prevBtn.disabled = currentCharIndex <= 0;
    nextBtn.disabled = currentCharIndex >= currentCharacters.length - 1;
    pagerCounter.textContent = currentCharacters.length
      ? `${currentCharIndex + 1} / ${currentCharacters.length}`
      : "";
  }

  function goToCharIndex(idx) {
    if (!currentCharacters.length) return;
    const clamped = Math.max(0, Math.min(idx, currentCharacters.length - 1));
    if (clamped === currentCharIndex) {
      return;
    }
    currentCharIndex = clamped;
    Array.from(pagerPages.children).forEach((btn, i) => {
      const active = i === clamped;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    updatePagerNav();
    showActiveCharCard();
    const activeBtn = pagerPages.children[clamped];
    if (activeBtn && activeBtn.scrollIntoView) {
      activeBtn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
  }

  function showActiveCharCard() {
    if (speechSupported) {
      window.speechSynthesis.cancel();
    }
    const char = currentCharacters[currentCharIndex];
    if (!char) {
      cards.innerHTML = "";
      return;
    }
    cards.innerHTML = "";
    cards.append(renderCard(getEntry(char) || fallbackRecord(char)));
  }

  async function renderCharacters(characters, sourceText) {
    if (!characters.length) {
      hidePager();
      currentCharacters = [];
      currentCharIndex = 0;
      cards.innerHTML = "";
      summary.textContent = "没有识别到汉字，请重新输入。";
      cards.append(createEmptyState(sourceText));
      return;
    }

    showLoading();
    await ensureShardsForChars(characters);

    currentCharacters = characters;
    currentCharIndex = 0;

    renderPager();
    showActiveCharCard();

    const missingCount = characters.filter((char) => !getEntry(char)).length;
    if (characters.length === 1) {
      summary.textContent = missingCount
        ? "暂无该字的内置数据，已展示可用字段。"
        : "认真学这个字吧～";
    } else {
      summary.textContent = missingCount
        ? `共 ${characters.length} 个字，其中 ${missingCount} 个暂无数据。点击下方汉字逐字学习～`
        : `共 ${characters.length} 个字，点击下方汉字逐字学习～`;
    }
  }

  async function renderSimpleCards(terms, options) {
    hidePager();
    currentCharacters = [];
    currentCharIndex = 0;
    if (!terms.length) {
      cards.innerHTML = "";
      summary.textContent = "没有识别到可查询的内容，请用“、”分割后重新输入。";
      cards.append(createEmptyState(""));
      return;
    }

    showLoading();
    await ensureShardsForTerms(terms);

    cards.innerHTML = "";
    const fragment = document.createDocumentFragment();
    const missingCount = terms.filter((term) => !getEntry(term)).length;
    terms.forEach((term) => {
      fragment.append(options.render(term, getEntry(term)));
    });

    cards.append(fragment);
    summary.textContent = missingCount
      ? `已展示 ${terms.length} 项，其中 ${missingCount} 项暂无内置数据。`
      : `已展示 ${terms.length} 项。`;
  }

  function createSimpleCard(title, subtitle) {
    const node = simpleTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector("h3").textContent = title;
    node.querySelector("p").textContent = subtitle;
    return node;
  }

  function createInfoBlock(title, values) {
    const block = document.createElement("section");
    block.className = "simple-block";

    const heading = document.createElement("h4");
    heading.textContent = title;
    block.append(heading);

    const list = document.createElement("ul");
    list.className = "word-list";
    renderList(list, values, "暂无", "word-chip", true);
    block.append(list);

    return block;
  }

  function sentenceValues(entry) {
    if (!entry) {
      return [];
    }
    if (Array.isArray(entry.sentences)) {
      return entry.sentences.slice(0, 3);
    }
    return [
      entry.sentences && entry.sentences.beginner,
      entry.sentences && entry.sentences.intermediate,
      entry.sentences && entry.sentences.advanced
    ].filter(Boolean);
  }

  function generatedSentenceValues(term, entry) {
    const values = sentenceValues(entry);
    if (values.length) {
      return values;
    }
    if (!term) {
      return [];
    }

    const words = entry && Array.isArray(entry.words) && entry.words.length ? entry.words : commonWordsFor(term);
    if (words.length >= 3) {
      return [`我喜欢${words[0]}。`, `我们一起了解${words[1]}。`, `老师给我们讲了${words[2]}。`];
    }
    if (words.length === 2) {
      return [`我喜欢${words[0]}。`, `我们一起了解${words[1]}。`, `${words[0]}让课堂更有趣。`];
    }
    if (words.length === 1) {
      return [`我喜欢${words[0]}。`, `${words[0]}让课堂更有趣。`, `大家一起了解${words[0]}。`];
    }

    return [`我喜欢${term}。`, `课文里写到了${term}。`, `${term}让课堂更有趣。`];
  }

  function renderMeaningCard(term, entry) {
    const node = createSimpleCard(term, "近义词 / 反义词");
    const body = node.querySelector(".simple-card-body");
    body.append(createInfoBlock("近义词", entry ? entry.synonyms : []));
    body.append(createInfoBlock("反义词", entry ? entry.antonyms : []));
    return node;
  }

  function renderWordCard(term, entry) {
    const node = createSimpleCard(term, "常见组词");
    const body = node.querySelector(".simple-card-body");
    body.append(createInfoBlock("组词", entry ? (entry.words || []).slice(0, 5) : []));
    return node;
  }

  function renderSentenceCard(term, entry) {
    const node = createSimpleCard(term, "3 条造句");
    const body = node.querySelector(".simple-card-body");
    const list = document.createElement("div");
    list.className = "sentence-list";

    const values = generatedSentenceValues(term, entry);
    const safeValues = values.length ? values : ["暂无", "暂无", "暂无"];
    safeValues.slice(0, 3).forEach((text, index) => {
      list.append(buildSentenceRow(`句子${index + 1}`, text));
    });

    body.append(list);
    return node;
  }

  async function renderCurrentFeature(sourceText, shouldSave) {
    if (currentFeature === "dictation") {
      renderDictationPage();
      return;
    }

    if (currentFeature === "history") {
      renderHistoryPage();
      return;
    }

    if (currentFeature === "hanzi") {
      const characters = uniqueChineseCharacters(sourceText);
      await renderCharacters(characters, sourceText);
      if (shouldSave) {
        saveHistory(sourceText, characters);
      }
      return;
    }

    const terms = splitTerms(sourceText);
    const renderers = {
      meaning: renderMeaningCard,
      words: renderWordCard,
      sentences: renderSentenceCard
    };

    await renderSimpleCards(terms, { render: renderers[currentFeature] });
    if (shouldSave) {
      saveHistory(sourceText, terms);
    }
  }

  function setFeature(feature) {
    currentFeature = feature;
    const copy = featureCopy[feature];
    searchTitle.textContent = copy.title;
    searchDescription.textContent = copy.description;
    input.placeholder = copy.placeholder;
    input.disabled = false;
    updateClearInputButton();
    document.querySelector("#input-help").textContent = copy.help;
    resultsTitle.textContent = copy.resultsTitle;
    searchPanel.hidden = feature === "history" || feature === "dictation";

    navItems.forEach((item) => {
      const isActive = item.dataset.feature === feature;
      item.classList.toggle("active", isActive);
      if (isActive) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });

    if (feature === "dictation") {
      renderDictationPage();
    } else if (feature === "history") {
      renderHistoryPage();
    } else if (feature === "hanzi") {
      const source = input.value || defaultCharacters.join("");
      renderCharacters(uniqueChineseCharacters(source), source);
    } else {
      renderSimpleCards(splitTerms(input.value), {
        render: {
          meaning: renderMeaningCard,
          words: renderWordCard,
          sentences: renderSentenceCard
        }[feature]
      });
    }
  }

  async function saveHistory(query, characters) {
    if (!query || !characters.length) {
      return;
    }

    try {
      await fetch("/api/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          feature: currentFeature,
          query,
          characters: characters.join("")
        })
      });
      await loadHistory();
    } catch (error) {
      if (currentFeature === "history") {
        summary.textContent = "直接打开 HTML 时不会保存历史；启动本地服务后可使用。";
      }
    }
  }

  async function loadHistory() {
    try {
      const response = await fetch("/api/history?limit=50");
      if (!response.ok) {
        throw new Error("history unavailable");
      }

      const payload = await response.json();
      historyItems = payload.items || [];
      if (currentFeature === "history") {
        renderHistoryPage();
      }
    } catch (error) {
      historyItems = [];
      if (currentFeature === "history") {
        renderHistoryPage("直接打开 HTML 时不会保存历史；启动本地服务后可使用。");
      }
    }
  }

  async function loadDictationHistory() {
    try {
      const response = await fetch("/api/dictation/history");
      if (!response.ok) throw new Error("unavailable");
      const payload = await response.json();
      dictationHistoryItems = payload.items || [];
    } catch {
      dictationHistoryItems = [];
    }
  }

  function renderHistoryPage(message) {
    hidePager();
    currentCharacters = [];
    currentCharIndex = 0;
    cards.innerHTML = "";

    const panel = document.createElement("section");
    panel.className = "history-panel";

    const toolbar = document.createElement("div");
    toolbar.className = "history-toolbar";

    const filters = document.createElement("div");
    filters.className = "history-filters";

    const searchInput = document.createElement("input");
    searchInput.className = "history-search";
    searchInput.type = "search";
    searchInput.placeholder = "搜索记录";
    searchInput.setAttribute("aria-label", "搜索记录");

    const featureFilter = document.createElement("select");
    featureFilter.className = "history-feature-filter";
    featureFilter.setAttribute("aria-label", "按功能筛选");
    [
      ["all", "全部功能"],
      ["hanzi", "汉字"],
      ["meaning", "字义"],
      ["words", "组词"],
      ["sentences", "造句"],
      ["dictation", "听写"]
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      featureFilter.append(option);
    });

    const selectAllLabel = document.createElement("label");
    selectAllLabel.className = "history-select-all";
    const selectAll = document.createElement("input");
    selectAll.type = "checkbox";
    selectAll.id = "history-select-all";
    selectAllLabel.append(selectAll, document.createTextNode("全选"));

    const deleteButton = document.createElement("button");
    deleteButton.className = "history-delete-button";
    deleteButton.type = "button";
    deleteButton.textContent = "删除所选";
    deleteButton.disabled = true;

    filters.append(searchInput, featureFilter);
    toolbar.append(filters, selectAllLabel, deleteButton);
    panel.append(toolbar);

    if (!historyItems.length) {
      const empty = document.createElement("p");
      empty.className = "history-empty";
      empty.textContent = message || "暂无学习记录。";
      panel.append(empty);
      cards.append(panel);
      summary.textContent = message || "暂无学习记录。";
      return;
    }

    const list = document.createElement("div");
    list.className = "history-list";

    const renderRows = async () => {
      list.innerHTML = "";
      const keyword = searchInput.value.trim();
      const feature = featureFilter.value;

      // Load dictation history when needed (only fetch once per page load)
      if ((feature === "dictation" || feature === "all") && !dictationHistoryItems.length) {
        await loadDictationHistory();
      }

      const filteredItems = feature === "dictation"
        ? []
        : historyItems.filter((item) => {
            const featureMatched = feature === "all" || (item.feature || "hanzi") === feature;
            const text = `${item.query || ""}${item.characters || ""}${featureLabels[item.feature] || ""}`;
            return featureMatched && (!keyword || text.includes(keyword));
          });

      const filteredDictation = (feature === "dictation" || feature === "all")
        ? dictationHistoryItems.filter(item => {
            const text = `${item.characters || ""}${item.wrong_characters || ""}`;
            return !keyword || text.includes(keyword);
          })
        : [];

      if (!filteredItems.length && !filteredDictation.length) {
        const empty = document.createElement("p");
        empty.className = "history-empty";
        empty.textContent = "没有匹配的学习记录。";
        list.append(empty);
        summary.textContent = "没有匹配的学习记录。";
        deleteButton.disabled = true;
        selectAll.checked = false;
        selectAll.indeterminate = false;
        return;
      }

      // Render dictation history rows
      filteredDictation.forEach((item) => {
        const row = document.createElement("article");
        row.className = "history-row dictation-history-row";

        const spacer = document.createElement("span");
        spacer.style.width = "22px";

        const content = document.createElement("div");
        content.style.cssText = "flex: 1; display: grid; gap: 4px;";

        const titleRow = document.createElement("div");
        titleRow.style.cssText = "display: flex; align-items: center; gap: 10px; flex-wrap: wrap;";
        const chars = document.createElement("span");
        chars.className = "history-query";
        chars.textContent = item.characters || "";
        titleRow.append(chars);

        const badge = document.createElement("span");
        badge.style.cssText = "padding: 2px 8px; border-radius: 8px; font-size: 12px; font-weight: 700;";
        if (item.accuracy >= 80) {
          badge.style.background = "var(--green-soft)";
          badge.style.color = "var(--green)";
        } else if (item.accuracy >= 60) {
          badge.style.background = "var(--yellow-soft)";
          badge.style.color = "#b8860b";
        } else {
          badge.style.background = "#fff0ed";
          badge.style.color = "var(--brand)";
        }
        badge.textContent = `${item.accuracy}%`;
        titleRow.append(badge);
        content.append(titleRow);

        const meta = document.createElement("div");
        meta.className = "history-meta";
        const wrongChars = item.wrong_characters || "";
        const scoreText = `${item.correct_count}/${item.total_count} 正确`;
        meta.textContent = wrongChars
          ? `听写 · ${item.created_at || ""} · ${scoreText} · 错字：${wrongChars}`
          : `听写 · ${item.created_at || ""} · ${scoreText}`;
        content.append(meta);

        if (wrongChars && Array.from(wrongChars).length >= 2) {
          const retryBtn = document.createElement("button");
          retryBtn.type = "button";
          retryBtn.className = "dictation-retry-small";
          retryBtn.textContent = `重听错字（${Array.from(wrongChars).length}）`;
          retryBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            try {
              const resp = await fetch("/api/dictation/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ characters: Array.from(wrongChars) })
              });
              if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                alert(err.error || "启动失败");
                return;
              }
              const data = await resp.json();
              dictationSession = { characters: data.characters, total_count: data.total_count, current_index: 0, results: [] };
              setFeature("dictation");
              renderDictationQuestion(0);
            } catch {
              alert("无法连接到服务");
            }
          });
          content.append(retryBtn);
        }

        row.append(spacer, content);
        list.append(row);
      });

      filteredItems.forEach((item) => {
      const row = document.createElement("article");
      row.className = "history-row";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "history-checkbox";
      checkbox.value = item.id;
      checkbox.setAttribute("aria-label", `选择记录 ${item.query || item.characters}`);

      const content = document.createElement("button");
      content.className = "history-open-button";
      content.type = "button";
      content.dataset.feature = item.feature || "hanzi";
      content.dataset.query = item.query || item.characters;

      const title = document.createElement("span");
      title.className = "history-query";
      title.textContent = item.query || item.characters;

      const meta = document.createElement("span");
      meta.className = "history-meta";
      meta.textContent = `${featureLabels[item.feature] || "汉字"} · ${item.created_at || ""}`;

      content.append(title, meta);
      row.append(checkbox, content);
      list.append(row);
    });
      const totalShowing = filteredItems.length + filteredDictation.length;
      const totalCount = historyItems.length + (feature === "all" || feature === "dictation" ? dictationHistoryItems.length : 0);
      summary.textContent = `共 ${totalCount} 条学习记录，当前显示 ${totalShowing} 条。`;
      attachRowHandlers();
    };

    panel.append(list);
    cards.append(panel);

    const getCheckboxes = () => Array.from(panel.querySelectorAll(".history-checkbox"));
    const updateDeleteState = () => {
      const checkboxes = getCheckboxes();
      const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
      deleteButton.disabled = selectedCount === 0;
      deleteButton.textContent = selectedCount ? `删除所选（${selectedCount}）` : "删除所选";
      selectAll.checked = checkboxes.length > 0 && selectedCount === checkboxes.length;
      selectAll.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
    };

    const attachRowHandlers = () => {
      getCheckboxes().forEach((checkbox) => {
        checkbox.addEventListener("change", updateDeleteState);
      });
      updateDeleteState();
    };

    deleteButton.addEventListener("click", async () => {
      const ids = getCheckboxes().filter((checkbox) => checkbox.checked).map((checkbox) => Number(checkbox.value));
      await deleteHistory(ids);
    });

    selectAll.addEventListener("change", () => {
      getCheckboxes().forEach((checkbox) => {
        checkbox.checked = selectAll.checked;
      });
      updateDeleteState();
    });

    searchInput.addEventListener("input", renderRows);
    featureFilter.addEventListener("change", renderRows);

    list.addEventListener("click", (event) => {
      const button = event.target.closest(".history-open-button");
      if (!button) {
        return;
      }
      const targetFeature = button.dataset.feature || "hanzi";
      input.value = button.dataset.query || "";
      setFeature(featureCopy[targetFeature] ? targetFeature : "hanzi");
      renderCurrentFeature(input.value, false);
    });

    renderRows();
  }

  async function deleteHistory(ids) {
    if (!ids.length) {
      return;
    }

    try {
      const response = await fetch("/api/history", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids })
      });
      if (!response.ok) {
        throw new Error("delete failed");
      }
      await loadHistory();
    } catch (error) {
      summary.textContent = "删除失败，请确认本地服务正在运行。";
    }
  }


  // ============ Dictation Functions ============

  function renderDictationPage() {
    hidePager();
    currentCharacters = [];
    currentCharIndex = 0;
    cards.innerHTML = "";
    summary.textContent = "选择要听写的汉字开始练习。";

    // First check if there's an active session to resume
    fetch("/api/dictation/session")
      .then(r => r.ok ? r.json() : { active: false })
      .then(data => {
        if (data.active && data.session) {
          renderDictationResume(data);
        } else if (data.auto_completed && data.session) {
          dictationSession = data.session;
          renderDictationSummary(data.session);
        } else {
          renderDictationSetup();
        }
      })
      .catch(() => {
        renderDictationSetup("无法连接到服务，请确认本地服务正在运行。");
      });
  }

  function renderDictationResume(data) {
    // data has .session with optional .state and .auto_completed
    const session = data.session;

    // Auto-completed by server (all answered, refresh before clicking "view results")
    if (data.auto_completed) {
      dictationSession = session;
      renderDictationSummary(session);
      return;
    }

    const state = session.state;

    // If there is saved state with a wrong answer, restore that view directly
    if (state && !state.is_correct) {
      dictationSession = session;
      dictationCurrentState = state;
      dictationWrongAttempts = state.wrong_attempts || 0;
      dictationCurrentAnswer = session.characters[state.char_index];
      renderDictationResumeWrong(session, state);
      return;
    }

    // Otherwise show the resume banner
    const panel = document.createElement("div");
    panel.className = "dictation-panel";

    const banner = document.createElement("div");
    banner.className = "dictation-resume-banner";

    const title = document.createElement("h3");
    title.textContent = "有未完成的听写";
    banner.append(title);

    const desc = document.createElement("p");
    const done = session.results ? session.results.length : 0;
    desc.textContent = `已完成 ${done} / ${session.total_count} 题，要继续做完吗？`;
    banner.append(desc);

    const actions = document.createElement("div");
    actions.className = "dictation-resume-actions";

    const resumeBtn = document.createElement("button");
    resumeBtn.type = "button";
    resumeBtn.className = "dictation-start-btn";
    resumeBtn.textContent = "继续听写";
    resumeBtn.addEventListener("click", () => {
      dictationSession = session;
      const nextIdx = session.current_index || 0;
      if (nextIdx >= session.total_count) {
        completeDictation(session);
      } else {
        renderDictationQuestion(nextIdx);
      }
    });

    const newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "dictation-new-btn";
    newBtn.textContent = "重新开始";
    newBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/dictation/session", { method: "DELETE" });
      } catch {}
      dictationSession = null;
      renderDictationSetup();
    });

    actions.append(resumeBtn, newBtn);
    banner.append(actions);
    panel.append(banner);
    cards.append(panel);
  }

  function renderDictationResumeWrong(session, state) {
    cards.innerHTML = "";
    const index = state.char_index;
    const correctChar = session.characters[index];
    dictationCurrentAnswer = correctChar;
    dictationWrongAttempts = state.wrong_attempts || 0;

    const panel = document.createElement("div");
    panel.className = "dictation-panel";

    const card = document.createElement("div");
    card.className = "dictation-card";

    // Progress
    const progress = document.createElement("div");
    progress.className = "dictation-progress";
    progress.textContent = `第 ${index + 1} 题 / 共 ${session.total_count} 题`;
    card.append(progress);

    // Question area
    const question = document.createElement("div");
    question.className = "dictation-question";

    const speakBtn = document.createElement("button");
    speakBtn.type = "button";
    speakBtn.className = "dictation-speak-btn";
    speakBtn.innerHTML = '<span class="speak-icon" aria-hidden="true">🔊</span><span>点我听读音</span>';
    speakBtn.setAttribute("aria-label", "点击朗读这个字");
    speakBtn.addEventListener("click", () => {
      if (speakBtn.disabled) return;
      speakBtn.disabled = true;
      speakText(correctChar, {
        rate: 0.7,
        onend: () => { speakBtn.disabled = false; },
        onerror: () => { speakBtn.disabled = false; }
      });
    });
    question.append(speakBtn);

    const hint = document.createElement("p");
    hint.style.cssText = "margin-top: 10px; color: var(--muted); font-size: 15px;";
    hint.textContent = "先听读音，再写下你听到的字吧～";
    question.append(hint);
    card.append(question);

    // Answer form
    const answerForm = document.createElement("div");
    answerForm.className = "dictation-answer-form";

    const answerInput = document.createElement("input");
    answerInput.className = "dictation-answer-input";
    answerInput.type = "text";
    answerInput.inputMode = "text";
    answerInput.placeholder = "改正后再输入";
    answerInput.setAttribute("aria-label", "输入你听到的字");
    answerInput.maxLength = 1;
    answerInput.autocomplete = "off";

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "dictation-submit-btn";
    submitBtn.textContent = "提交";

    answerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submitBtn.click();
    });

    submitBtn.addEventListener("click", async () => {
      if (dictationSubmitting) return;
      const answer = answerInput.value.trim();
      if (!answer) {
        const feedbackArea = panel.querySelector(".dictation-feedback-area");
        if (feedbackArea) {
          feedbackArea.innerHTML = '<p style="color: var(--brand); font-weight: 600; text-align: center; margin-top: 8px;">请先输入答案再提交哦～</p>';
        }
        answerInput.focus();
        return;
      }

      dictationSubmitting = true;
      submitBtn.disabled = true;
      answerInput.disabled = true;

      let serverResult;
      try {
        const resp = await fetch("/api/dictation/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            position: index,
            character: answer
          })
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          const feedbackArea = panel.querySelector(".dictation-feedback-area");
          if (feedbackArea) {
            feedbackArea.innerHTML = `<p style="color: var(--brand); font-weight: 600; text-align: center; margin-top: 8px;">${err.error || "提交失败，请稍后重试。"}</p>`;
          }
          submitBtn.disabled = false;
          answerInput.disabled = false;
          dictationSubmitting = false;
          return;
        }
        serverResult = await resp.json();
      } catch {
        const feedbackArea = panel.querySelector(".dictation-feedback-area");
        if (feedbackArea) {
          feedbackArea.innerHTML = '<p style="color: var(--brand); font-weight: 600; text-align: center; margin-top: 8px;">无法连接到服务，请确认本地服务正在运行。</p>';
        }
        submitBtn.disabled = false;
        answerInput.disabled = false;
        dictationSubmitting = false;
        return;
      }

      const isCorrect = serverResult.correct;
      const attempts = serverResult.wrong_attempts;

      dictationCurrentState = { position: index, wrongAttempts: attempts, lastAnswer: answer, isCorrect };

      const existingIdx = session.results.findIndex(r => r.char_index === index);
      const resultEntry = { char_index: index, character: isCorrect ? answer : correctChar, correct: isCorrect ? 1 : 0, wrong_attempts: attempts };
      if (existingIdx >= 0) session.results[existingIdx] = resultEntry;
      else session.results.push(resultEntry);

      if (isCorrect) {
        dictationWrongAttempts = attempts;
        renderDictationFeedback(panel, index, true, answer, correctChar, session);
      } else {
        dictationWrongAttempts = attempts;
        renderDictationWrongFeedback(panel, index, answer, correctChar, answerInput, submitBtn, session);
      }
    });

    answerForm.append(answerInput, submitBtn);
    card.append(answerForm);

    // Show wrong feedback immediately (restored state)
    const feedbackArea = document.createElement("div");
    feedbackArea.className = "dictation-feedback-area";
    const feedback = document.createElement("div");
    feedback.className = "dictation-feedback is-wrong";

    const feedbackTitle = document.createElement("p");
    feedbackTitle.className = "dictation-feedback-title";
    feedbackTitle.textContent = "❌ 写错了";
    feedback.append(feedbackTitle);

    const correctLabel = document.createElement("p");
    correctLabel.style.cssText = "margin: 6px 0 0; color: var(--ink-soft); font-size: 16px;";
    correctLabel.textContent = "正确答案是：";
    feedback.append(correctLabel);

    const correctCharEl = document.createElement("span");
    correctCharEl.className = "dictation-feedback-char";
    correctCharEl.textContent = correctChar;
    feedback.append(correctCharEl);

    const retryHint = document.createElement("p");
    retryHint.style.cssText = "margin: 8px 0 0; color: var(--muted); font-size: 15px;";
    retryHint.textContent = "改正后再提交吧～";
    feedback.append(retryHint);

    feedbackArea.append(feedback);
    card.append(feedbackArea);

    panel.append(card);
    cards.append(panel);

    setTimeout(() => answerInput.focus(), 100);
  }

  function renderDictationSetup(message) {
    cards.innerHTML = "";
    dictationSession = null;
    dictationSelected = [];

    const panel = document.createElement("div");
    panel.className = "dictation-panel";

    const card = document.createElement("div");
    card.className = "dictation-card";

    const title = document.createElement("h3");
    title.textContent = "选择要听写的汉字";
    card.append(title);

    const desc = document.createElement("p");
    desc.textContent = "从下方查过的字中挑选，或在输入框中手动输入要听写的字（2~20 个，重复自动去重）。";
    card.append(desc);

    // Text input area
    const textarea = document.createElement("textarea");
    textarea.className = "dictation-textarea";
    textarea.placeholder = "也可以在这里手动输入汉字…";
    textarea.setAttribute("aria-label", "手动输入要听写的汉字");
    textarea.addEventListener("input", () => {
      const raw = textarea.value;
      const nonChinese = raw.replace(/[\p{Script=Han}]/gu, "").replace(/[\s、，,]/gu, "").trim();
      if (nonChinese) {
        updateDictationError(panel, "输入中包含非汉字内容，已自动忽略：" + nonChinese);
      } else {
        updateDictationError(panel, null);
      }

      const manual = Array.from(raw).filter(c => isChineseCharacter(c));
      const seen = new Set();
      const unique = [];
      for (const c of manual) {
        if (!seen.has(c)) { seen.add(c); unique.push(c); }
      }

      // Remove old manual chars from selection, add new ones
      const poolSelected = dictationSelected.filter(c => !dictationManualChars.includes(c));
      const newManual = unique.filter(c => !poolSelected.includes(c));
      dictationSelected = [...poolSelected, ...newManual];
      dictationManualChars = unique;

      // Update pool button states
      panel.querySelectorAll(".dictation-char-btn").forEach(btn => {
        btn.classList.toggle("selected", dictationSelected.includes(btn.dataset.char));
      });

      updateDictationSelectedDisplay(panel);
    });
    card.append(textarea);

    // Error message
    const errorEl = document.createElement("p");
    errorEl.className = "dictation-error";
    errorEl.hidden = true;
    card.append(errorEl);

    // Character pool from history
    const poolSection = document.createElement("div");
    poolSection.className = "dictation-pool";

    const poolHeader = document.createElement("div");
    poolHeader.className = "dictation-pool-header";
    const poolTitle = document.createElement("h4");
    poolTitle.textContent = "从查过的字中选：";
    poolHeader.append(poolTitle);

    const poolSearch = document.createElement("input");
    poolSearch.className = "dictation-pool-search";
    poolSearch.type = "search";
    poolSearch.placeholder = "搜索字…";
    poolSearch.setAttribute("aria-label", "搜索可选的字");
    poolHeader.append(poolSearch);
    poolSection.append(poolHeader);

    const poolChars = document.createElement("div");
    poolChars.className = "dictation-pool-chars";
    poolSection.append(poolChars);
    card.append(poolSection);

    // Selected chars display
    const selectedSection = document.createElement("div");
    selectedSection.className = "dictation-selected";
    const selectedTitle = document.createElement("h4");
    selectedTitle.textContent = "已选汉字：";
    selectedSection.append(selectedTitle);
    const selectedChars = document.createElement("div");
    selectedChars.className = "dictation-selected-chars";
    selectedSection.append(selectedChars);
    card.append(selectedSection);

    // Actions
    const actions = document.createElement("div");
    actions.className = "dictation-actions";
    const startBtn = document.createElement("button");
    startBtn.type = "button";
    startBtn.className = "dictation-start-btn";
    startBtn.textContent = "开始听写";
    startBtn.disabled = true;
    startBtn.addEventListener("click", async () => {
      if (dictationSelected.length < 2) {
        updateDictationError(panel, "至少需要选 2 个不重复的汉字哦～");
        return;
      }
      if (dictationSelected.length > 20) {
        updateDictationError(panel, "一次最多只能听写 20 个字哦～");
        return;
      }
      try {
        const resp = await fetch("/api/dictation/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ characters: dictationSelected })
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          updateDictationError(panel, err.error || "启动失败，请稍后重试。");
          return;
        }
        const data = await resp.json();
        dictationSession = { characters: data.characters, total_count: data.total_count, current_index: 0, results: [] };
        renderDictationQuestion(0);
      } catch (e) {
        updateDictationError(panel, "无法连接到服务，请确认本地服务正在运行。");
      }
    });
    actions.append(startBtn);
    card.append(actions);

    panel.append(card);
    cards.append(panel);

    if (message) {
      updateDictationError(panel, message);
    }

    // Load character pool
    loadDictationPool(panel, poolChars, poolSearch);

    // Store references for updates
    panel._startBtn = startBtn;
    panel._selectedDisplay = selectedChars;
    panel._errorEl = errorEl;

    updateDictationSelectedDisplay(panel);
  }

  function updateDictationError(panel, msg) {
    const errorEl = panel.querySelector(".dictation-error") || panel._errorEl;
    if (!errorEl) return;
    if (msg) {
      errorEl.textContent = msg;
      errorEl.hidden = false;
    } else {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
  }

  function updateDictationSelectedDisplay(panel) {
    const display = panel.querySelector(".dictation-selected-chars") || panel._selectedDisplay;
    const startBtn = panel.querySelector(".dictation-start-btn") || panel._startBtn;
    if (!display) return;
    display.innerHTML = "";
    if (!dictationSelected.length) {
      const empty = document.createElement("span");
      empty.className = "dictation-selected-empty";
      empty.textContent = "还没选字哦～";
      display.append(empty);
    } else {
      dictationSelected.forEach(char => {
        const chip = document.createElement("span");
        chip.className = "dictation-selected-char";
        chip.textContent = char;
        chip.title = "点击移除";
        chip.style.cursor = "pointer";
        chip.addEventListener("click", () => {
          dictationSelected = dictationSelected.filter(c => c !== char);
          // Also uncheck in pool
          const poolBtn = panel.querySelector(`.dictation-char-btn[data-char="${char}"]`);
          if (poolBtn) poolBtn.classList.remove("selected");
          updateDictationSelectedDisplay(panel);
        });
        display.append(chip);
      });
    }
    if (startBtn) {
      startBtn.disabled = dictationSelected.length < 2;
    }
  }

  async function loadDictationPool(panel, poolContainer, poolSearch) {
    try {
      const resp = await fetch("/api/dictation/characters");
      if (!resp.ok) throw new Error("unavailable");
      const data = await resp.json();
      dictationPool = data.characters || [];
    } catch {
      dictationPool = [];
      poolContainer.innerHTML = "";
      const msg = document.createElement("span");
      msg.style.color = "var(--muted)";
      msg.style.fontSize = "15px";
      msg.textContent = "暂无查过的字。请先去其他功能查一些字，或直接手动输入。";
      poolContainer.append(msg);
      return;
    }

    function renderPool(filter) {
      poolContainer.innerHTML = "";
      const filtered = filter
        ? dictationPool.filter(c => c.includes(filter))
        : dictationPool;

      if (!filtered.length) {
        const msg = document.createElement("span");
        msg.style.color = "var(--muted)";
        msg.style.fontSize = "15px";
        msg.textContent = filter ? "没有匹配的字。" : "暂无可选的字。";
        poolContainer.append(msg);
        return;
      }

      filtered.forEach(char => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "dictation-char-btn";
        btn.textContent = char;
        btn.dataset.char = char;
        btn.setAttribute("aria-label", `选择汉字：${char}`);
        if (dictationSelected.includes(char)) {
          btn.classList.add("selected");
        }
        btn.addEventListener("click", () => {
          if (dictationSelected.includes(char)) {
            dictationSelected = dictationSelected.filter(c => c !== char);
            btn.classList.remove("selected");
          } else {
            if (dictationSelected.length >= 20) {
              updateDictationError(panel, "最多只能选 20 个字哦～");
              return;
            }
            dictationSelected.push(char);
            btn.classList.add("selected");
          }
          updateDictationSelectedDisplay(panel);
        });
        poolContainer.append(btn);
      });
    }

    renderPool("");
    poolSearch.addEventListener("input", () => renderPool(poolSearch.value.trim()));
  }

  function renderDictationQuestion(index) {
    cards.innerHTML = "";
    const session = dictationSession;
    const char = session.characters[index];
    dictationCurrentAnswer = char;
    dictationWrongAttempts = 0;
    dictationSubmitting = false;

    const panel = document.createElement("div");
    panel.className = "dictation-panel";

    const card = document.createElement("div");
    card.className = "dictation-card";

    // Progress
    const progress = document.createElement("div");
    progress.className = "dictation-progress";
    progress.textContent = `第 ${index + 1} 题 / 共 ${session.total_count} 题`;
    card.append(progress);

    // Question area
    const question = document.createElement("div");
    question.className = "dictation-question";

    const speakBtn = document.createElement("button");
    speakBtn.type = "button";
    speakBtn.className = "dictation-speak-btn";
    speakBtn.innerHTML = '<span class="speak-icon" aria-hidden="true">🔊</span><span>点我听读音</span>';
    speakBtn.setAttribute("aria-label", "点击朗读这个字");
    speakBtn.addEventListener("click", () => {
      if (speakBtn.disabled) return;
      speakBtn.disabled = true;
      speakText(char, {
        rate: 0.7,
        onend: () => { speakBtn.disabled = false; },
        onerror: () => { speakBtn.disabled = false; }
      });
    });
    question.append(speakBtn);

    const hint = document.createElement("p");
    hint.style.cssText = "margin-top: 10px; color: var(--muted); font-size: 15px;";
    hint.textContent = "先听读音，再写下你听到的字吧～";
    question.append(hint);
    card.append(question);

    // Answer form
    const answerForm = document.createElement("div");
    answerForm.className = "dictation-answer-form";

    const answerInput = document.createElement("input");
    answerInput.className = "dictation-answer-input";
    answerInput.type = "text";
    answerInput.inputMode = "text";
    answerInput.placeholder = "写你听到的字";
    answerInput.setAttribute("aria-label", "输入你听到的字");
    answerInput.maxLength = 1;
    answerInput.autocomplete = "off";

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "dictation-submit-btn";
    submitBtn.textContent = "提交";

    answerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        submitBtn.click();
      }
    });

    submitBtn.addEventListener("click", async () => {
      if (dictationSubmitting) return;
      const answer = answerInput.value.trim();
      if (!answer) {
        const feedbackArea = panel.querySelector(".dictation-feedback-area");
        if (feedbackArea) {
          feedbackArea.innerHTML = '<p style="color: var(--brand); font-weight: 600; text-align: center; margin-top: 8px;">请先输入答案再提交哦～</p>';
        }
        answerInput.focus();
        return;
      }

      dictationSubmitting = true;
      submitBtn.disabled = true;
      answerInput.disabled = true;

      // Save to server and let it verify correctness
      let serverResult;
      try {
        const resp = await fetch("/api/dictation/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            position: index,
            character: answer
          })
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          const feedbackArea = panel.querySelector(".dictation-feedback-area");
          if (feedbackArea) {
            feedbackArea.innerHTML = `<p style="color: var(--brand); font-weight: 600; text-align: center; margin-top: 8px;">${err.error || "提交失败，请稍后重试。"}</p>`;
          }
          submitBtn.disabled = false;
          answerInput.disabled = false;
          dictationSubmitting = false;
          return;
        }
        serverResult = await resp.json();
      } catch {
        const feedbackArea = panel.querySelector(".dictation-feedback-area");
        if (feedbackArea) {
          feedbackArea.innerHTML = '<p style="color: var(--brand); font-weight: 600; text-align: center; margin-top: 8px;">无法连接到服务，请确认本地服务正在运行。</p>';
        }
        submitBtn.disabled = false;
        answerInput.disabled = false;
        dictationSubmitting = false;
        return;
      }

      const isCorrect = serverResult.correct;
      const attempts = serverResult.wrong_attempts;

      dictationCurrentState = {
        position: index,
        wrongAttempts: attempts,
        lastAnswer: answer,
        isCorrect: isCorrect
      };

      // Update local session results
      const existingIdx = session.results.findIndex(r => r.char_index === index);
      const resultEntry = { char_index: index, character: isCorrect ? answer : dictationCurrentAnswer, correct: isCorrect ? 1 : 0, wrong_attempts: attempts };
      if (existingIdx >= 0) {
        session.results[existingIdx] = resultEntry;
      } else {
        session.results.push(resultEntry);
      }

      if (isCorrect) {
        dictationWrongAttempts = attempts;
        renderDictationFeedback(panel, index, true, answer, dictationCurrentAnswer, session);
      } else {
        dictationWrongAttempts = attempts;
        renderDictationWrongFeedback(panel, index, answer, dictationCurrentAnswer, answerInput, submitBtn, session);
      }
    });

    answerForm.append(answerInput, submitBtn);
    card.append(answerForm);

    // Feedback area (placeholder)
    const feedback = document.createElement("div");
    feedback.className = "dictation-feedback-area";
    card.append(feedback);

    panel.append(card);
    cards.append(panel);

    // Auto-focus and auto-speak
    setTimeout(() => {
      answerInput.focus();
      speakBtn.click();
    }, 100);
  }

  function renderDictationWrongFeedback(panel, index, wrongAnswer, correctChar, answerInput, submitBtn, session) {
    const feedbackArea = panel.querySelector(".dictation-feedback-area");
    if (!feedbackArea) return;

    feedbackArea.innerHTML = "";
    const feedback = document.createElement("div");
    feedback.className = "dictation-feedback is-wrong";

    const title = document.createElement("p");
    title.className = "dictation-feedback-title";
    title.textContent = "❌ 写错了";
    feedback.append(title);

    const correctLabel = document.createElement("p");
    correctLabel.style.cssText = "margin: 6px 0 0; color: var(--ink-soft); font-size: 16px;";
    correctLabel.textContent = `正确答案是：`;
    feedback.append(correctLabel);

    const correctCharEl = document.createElement("span");
    correctCharEl.className = "dictation-feedback-char";
    correctCharEl.textContent = correctChar;
    feedback.append(correctCharEl);

    const retryHint = document.createElement("p");
    retryHint.style.cssText = "margin: 8px 0 0; color: var(--muted); font-size: 15px;";
    retryHint.textContent = "改正后再提交吧～";
    feedback.append(retryHint);

    feedbackArea.append(feedback);

    // Reset for retry
    answerInput.value = "";
    answerInput.disabled = false;
    submitBtn.disabled = true;
    dictationSubmitting = false;
    answerInput.focus();
  }

  function renderDictationFeedback(panel, index, isCorrect, answer, correctChar, session) {
    const feedbackArea = panel.querySelector(".dictation-feedback-area");
    if (!feedbackArea) return;

    feedbackArea.innerHTML = "";
    const feedback = document.createElement("div");
    feedback.className = `dictation-feedback ${isCorrect ? "is-correct" : "is-wrong"}`;

    const title = document.createElement("p");
    title.className = "dictation-feedback-title";
    title.textContent = isCorrect ? "✅ 写对啦！" : "❌ 写错了";
    feedback.append(title);

    if (!isCorrect || dictationWrongAttempts > 0) {
      const charEl = document.createElement("span");
      charEl.className = "dictation-feedback-char";
      charEl.textContent = correctChar;
      feedback.append(charEl);
    }

    if (dictationWrongAttempts > 0 && isCorrect) {
      const note = document.createElement("p");
      note.style.cssText = "margin: 4px 0 0; color: var(--muted); font-size: 14px;";
      note.textContent = `（改错了 ${dictationWrongAttempts} 次后改正）`;
      feedback.append(note);
    }

    // Next button
    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "dictation-next-btn";
    nextBtn.textContent = index + 1 >= session.total_count ? "查看结果" : "下一题";
    nextBtn.addEventListener("click", () => {
      dictationCurrentState = null;
      const nextIndex = index + 1;
      if (nextIndex >= session.total_count) {
        completeDictation(session);
      } else {
        session.current_index = nextIndex;
        renderDictationQuestion(nextIndex);
      }
    });
    feedback.append(nextBtn);

    feedbackArea.append(feedback);

    // Hide the answer form
    const answerForm = panel.querySelector(".dictation-answer-form");
    if (answerForm) answerForm.style.display = "none";

    setTimeout(() => nextBtn.focus(), 100);
  }

  async function completeDictation(session) {
    try {
      const resp = await fetch("/api/dictation/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        loadDictationHistory();
        renderDictationCompleteError(session, err.error || "保存结果失败，请稍后重试。");
        return;
      }
      const data = await resp.json();
      session.total = data.total;
      session.correct = data.correct;
      session.wrong_characters = data.wrong_characters;
      session.accuracy = data.accuracy;
    } catch {
      loadDictationHistory();
      renderDictationCompleteError(session, "无法连接到服务，结果未能保存。请确认本地服务正在运行。");
      return;
    }
    loadDictationHistory();
    renderDictationSummary(session);
  }

  function renderDictationCompleteError(session, errorMsg) {
    cards.innerHTML = "";
    dictationSession = null;

    const panel = document.createElement("div");
    panel.className = "dictation-panel";
    const card = document.createElement("div");
    card.className = "dictation-card";

    const errorBox = document.createElement("div");
    errorBox.style.cssText = "text-align: center; padding: 24px 16px;";

    const title = document.createElement("h3");
    title.style.cssText = "color: var(--brand); margin: 0 0 8px;";
    title.textContent = "⚠️ 提交失败";
    errorBox.append(title);

    const msg = document.createElement("p");
    msg.style.cssText = "color: var(--ink-soft); font-size: 16px; margin: 0 0 16px;";
    msg.textContent = errorMsg;
    errorBox.append(msg);

    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "dictation-retry-btn";
    retryBtn.textContent = "重新提交";
    retryBtn.addEventListener("click", () => {
      completeDictation(session);
    });
    errorBox.append(retryBtn);

    card.append(errorBox);
    panel.append(card);
    cards.append(panel);

    const total = session.total_count || session.characters.length;
    summary.textContent = `听写完成！共 ${total} 题，但结果保存失败。`;
  }

  function renderDictationSummary(session) {
    cards.innerHTML = "";
    dictationSession = null;

    const panel = document.createElement("div");
    panel.className = "dictation-panel";

    const card = document.createElement("div");
    card.className = "dictation-card";

    // Summary header
    const summaryEl = document.createElement("div");
    summaryEl.className = "dictation-summary";

    const score = document.createElement("div");
    score.className = "dictation-summary-score";
    const total = session.total_count || session.total || session.characters.length;
    const correct = session.correct != null ? session.correct : (session.results ? session.results.filter(r => r.wrong_attempts === 0 && r.correct).length : 0);
    const wrong = total - correct;
    score.textContent = `听写完成！共 ${total} 题`;
    summaryEl.append(score);

    const accuracy = document.createElement("div");
    accuracy.className = "dictation-summary-accuracy";
    const acc = session.accuracy != null ? session.accuracy : (total > 0 ? Math.round(correct / total * 1000) / 10 : 0);
    accuracy.textContent = `答对 ${correct} 题，答错 ${wrong} 题，正确率 ${acc}%`;
    summaryEl.append(accuracy);

    card.append(summaryEl);

    // Detail rows
    if (session.results && session.results.length) {
      const detail = document.createElement("div");
      detail.className = "dictation-summary-detail";

      session.results.forEach(result => {
        const row = document.createElement("div");
        const firstTryCorrect = result.correct && result.wrong_attempts === 0;
        row.className = `dictation-summary-row ${firstTryCorrect ? "is-correct" : "is-wrong"}`;

        const char = document.createElement("span");
        char.className = "dictation-summary-char";
        char.textContent = result.character;
        row.append(char);

        const label = document.createElement("span");
        label.className = "dictation-summary-label";
        if (result.correct && result.wrong_attempts === 0) {
          label.textContent = "一次写对 ✅";
        } else if (result.correct) {
          label.textContent = `改正后写对（错了 ${result.wrong_attempts} 次）`;
        } else {
          label.textContent = "写错 ❌";
        }
        row.append(label);

        detail.append(row);
      });

      card.append(detail);
    }

    // Action buttons
    const actions = document.createElement("div");
    actions.className = "dictation-summary-actions";

    const wrongChars = session.wrong_characters || (session.results ? session.results.filter(r => r.wrong_attempts > 0).map(r => r.character) : []);

    if (wrongChars.length > 0) {
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "dictation-retry-btn";
      retryBtn.textContent = `错字重听（${wrongChars.length} 个）`;
      retryBtn.addEventListener("click", async () => {
        try {
          const resp = await fetch("/api/dictation/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ characters: wrongChars, retry: true })
          });
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            alert(err.error || "启动失败");
            return;
          }
          const data = await resp.json();
          dictationSession = { characters: data.characters, total_count: data.total_count, current_index: 0, results: [] };
          renderDictationQuestion(0);
        } catch {
          alert("无法连接到服务");
        }
      });
      actions.append(retryBtn);
    }

    const newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "dictation-new-btn";
    newBtn.textContent = "再来一次";
    newBtn.addEventListener("click", () => {
      renderDictationSetup();
    });
    actions.append(newBtn);

    card.append(actions);
    panel.append(card);
    cards.append(panel);

    summary.textContent = `听写完成！共 ${total} 题，正确率 ${acc}%。`;
  }

  function createEmptyState(sourceText) {
    const empty = document.createElement("div");
    empty.className = "empty-state";

    const title = document.createElement("h3");
    title.textContent = "没有可展示的内容";
    empty.append(title);

    const tip = document.createElement("p");
    tip.textContent = sourceText ? "输入内容里没有可识别的汉字。" : "请输入内容开始学习。";
    empty.append(tip);

    return empty;
  }

  function updateClearInputButton() {
    clearInputButton.hidden = !input.value;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const rawValue = input.value.trim();
    renderCurrentFeature(rawValue, true);
  });

  input.addEventListener("input", updateClearInputButton);

  clearInputButton.addEventListener("click", () => {
    input.value = "";
    updateClearInputButton();
    input.focus();
    renderCurrentFeature("", false);
  });

  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      setFeature(item.dataset.feature);
    });
  });

  printButton.addEventListener("click", () => {
    window.print();
  });

  prevBtn.addEventListener("click", () => {
    goToCharIndex(currentCharIndex - 1);
  });

  nextBtn.addEventListener("click", () => {
    goToCharIndex(currentCharIndex + 1);
  });

  document.addEventListener("keydown", (event) => {
    if (currentFeature !== "hanzi" || pager.hidden) return;
    if (currentCharacters.length <= 1) return;
    const active = document.activeElement;
    if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable)) {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      goToCharIndex(currentCharIndex - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      goToCharIndex(currentCharIndex + 1);
    }
  });

  renderCharacters(defaultCharacters, defaultCharacters.join(""));
  updateClearInputButton();
  loadHistory();
  loadDictationHistory();
})();
