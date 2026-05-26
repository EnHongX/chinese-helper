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
    dictation: {
      title: "听写复习",
      description: "从学过的字中挑选或手动输入，开始听写练习。",
      placeholder: "输入要听写的汉字（2～20个）",
      help: "重复的字只算一个。支持从查询记录中快速选取。",
      resultsTitle: "听写练习"
    },
    history: {
      title: "学习记录",
      description: "查看本地查询历史，可单选或多选删除记录。",
      placeholder: "",
      help: "点击记录内容会自动切换到对应功能并回填查询。",
      resultsTitle: "学习记录"
    }
  };

  const featureLabels = {
    hanzi: "汉字",
    meaning: "字义",
    words: "组词",
    sentences: "造句",
    dictation: "听写",
    history: "记录"
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

    if (feature === "history") {
      renderHistoryPage();
    } else if (feature === "dictation") {
      renderDictationPage();
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

    const renderRows = () => {
      list.innerHTML = "";
      const keyword = searchInput.value.trim();
      const feature = featureFilter.value;
      const filteredItems = historyItems.filter((item) => {
        const featureMatched = feature === "all" || (item.feature || "hanzi") === feature;
        const text = `${item.query || ""}${item.characters || ""}${featureLabels[item.feature] || ""}`;
        return featureMatched && (!keyword || text.includes(keyword));
      });

      if (!filteredItems.length) {
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
      summary.textContent = `共 ${historyItems.length} 条学习记录，当前显示 ${filteredItems.length} 条。`;
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

  // ==================== 听写 Dictation ====================

  let dictationMode = "setup";
  let dictationSession = null;
  let dictationCharIndex = 0;
  let dictationChars = [];
  let dictationAttempts = [];
  let dictationRetryIndex = -1;
  let dictationSubmitting = false;
  let pastDictationResults = [];

  async function renderDictationPage() {
    hidePager();
    currentCharacters = [];
    currentCharIndex = 0;
    cards.innerHTML = "";
    searchPanel.hidden = true;
    if (speechSupported) window.speechSynthesis.cancel();

    let activeSession = null;
    try {
      const r = await fetch("/api/dictation/session");
      if (r.ok) activeSession = (await r.json()).session || null;
    } catch (_) { /* server off */ }

    // Pre-load history results in background (needed for both resume and setup paths).
    loadDictationResults();

    if (activeSession) {
      dictationMode = "practice";
      dictationSession = activeSession;
      dictationChars = Array.from(activeSession.characters);
      dictationAttempts = activeSession.attempts || [];
      const attemptedSet = new Set(dictationAttempts.map((a) => a.char_index));
      dictationCharIndex = 0;
      for (let i = 0; i < dictationChars.length; i++) {
        if (!attemptedSet.has(i)) { dictationCharIndex = i; break; }
        if (i === dictationChars.length - 1) dictationCharIndex = dictationChars.length;
      }
      renderDictationPractice();
      return;
    }

    dictationMode = "setup";
    dictationSession = null;
    dictationChars = [];
    dictationAttempts = [];
    dictationCharIndex = 0;
    renderDictationSetup();
    loadDictationResults();
  }

  async function renderDictationSetup() {
    cards.innerHTML = "";
    const panel = document.createElement("section");
    panel.className = "dictation-panel";

    const resume = document.createElement("div");
    resume.className = "dictation-resume-slot";
    panel.append(resume);
    checkActiveDictation(resume);

    let historyChars = [];
    let serverOffline = false;
    try {
      const r = await fetch("/api/history?limit=50");
      if (r.ok) {
        const data = await r.json();
        const seen = new Set();
        (data.items || []).forEach((item) => {
          Array.from(item.characters || "").forEach((ch) => {
            if (isChineseCharacter(ch) && !seen.has(ch)) { seen.add(ch); historyChars.push(ch); }
          });
        });
      } else {
        serverOffline = true;
      }
    } catch (_) { serverOffline = true; }

    const selectedSet = new Set();

    const setup = document.createElement("div");
    setup.className = "dictation-setup";

    if (serverOffline) {
      const offline = document.createElement("p");
      offline.className = "dictation-hint dictation-offline";
      offline.textContent = "无法连接到服务器，请确认本地服务已启动，然后刷新页面。";
      setup.append(offline);
    }

    const histSec = document.createElement("div");
    histSec.className = "dictation-section";
    const histTitle = document.createElement("h4");
    histTitle.textContent = "从学过的字里挑选";
    histSec.append(histTitle);

    let picker = null;
    if (serverOffline) {
      const msg = document.createElement("p");
      msg.className = "dictation-hint";
      msg.textContent = "服务未启动，无法加载查字记录。";
      histSec.append(msg);
    } else if (!historyChars.length) {
      const msg = document.createElement("p");
      msg.className = "dictation-hint";
      msg.textContent = "还没有查过字，请先在“汉字”或“组词”等页面查询一些字，或手动输入要听写的字。";
      histSec.append(msg);
    } else {
      picker = document.createElement("div");
      picker.className = "dictation-picker";
      historyChars.forEach((ch) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "dictation-char-btn";
        b.textContent = ch;
        b.dataset.char = ch;
        picker.append(b);
      });
      histSec.append(picker);
    }
    setup.append(histSec);

    const manualSec = document.createElement("div");
    manualSec.className = "dictation-section";
    const manualTitle = document.createElement("h4");
    manualTitle.textContent = "或手动输入要听写的字";
    manualSec.append(manualTitle);

    const formWrap = document.createElement("div");
    formWrap.className = "dictation-input-row";
    const manualInput = document.createElement("input");
    manualInput.type = "text";
    manualInput.className = "dictation-manual-input";
    manualInput.placeholder = "例如：大小多少天地人";
    manualInput.inputMode = "text";
    manualInput.autocomplete = "off";
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "dictation-add-btn";
    addBtn.textContent = "添加";
    formWrap.append(manualInput, addBtn);
    manualSec.append(formWrap);

    const manualMsg = document.createElement("p");
    manualMsg.className = "dictation-message";
    manualSec.append(manualMsg);
    setup.append(manualSec);

    const selectedSec = document.createElement("div");
    selectedSec.className = "dictation-section";
    const selTitle = document.createElement("h4");
    selTitle.textContent = "已选汉字";
    selectedSec.append(selTitle);

    const tagList = document.createElement("div");
    tagList.className = "dictation-tag-list";
    selectedSec.append(tagList);

    const counter = document.createElement("p");
    counter.className = "dictation-counter";
    counter.textContent = "已选 0 / 20 个字（至少 2 个才能开始）";
    selectedSec.append(counter);

    const startBtn = document.createElement("button");
    startBtn.type = "button";
    startBtn.className = "dictation-start-btn";
    startBtn.textContent = "开始听写";
    startBtn.disabled = true;
    selectedSec.append(startBtn);
    setup.append(selectedSec);

    panel.append(setup);

    const resultsSlot = document.createElement("div");
    resultsSlot.className = "dictation-past-results";
    panel.append(resultsSlot);

    cards.append(panel);
    summary.textContent = serverOffline
      ? "无法连接到服务器，请启动服务后刷新页面。"
      : "选择或输入要听写的汉字，然后开始练习。";

    function refreshTags() {
      tagList.innerHTML = "";
      const arr = Array.from(selectedSet);
      arr.forEach((ch, idx) => {
        const tag = document.createElement("span");
        tag.className = "dictation-tag";
        tag.dataset.index = String(idx);
        const txt = document.createElement("span");
        txt.textContent = ch;
        const rm = document.createElement("span");
        rm.className = "dictation-tag-remove";
        rm.textContent = "×";
        rm.dataset.index = String(idx);
        tag.append(txt, rm);
        tagList.append(tag);
      });
      if (picker) {
        Array.from(picker.querySelectorAll(".dictation-char-btn")).forEach((btn) => {
          btn.classList.toggle("is-selected", selectedSet.has(btn.dataset.char));
        });
      }
      const n = selectedSet.size;
      counter.textContent = `已选 ${n} / 20 个字（至少 2 个才能开始）`;
      startBtn.disabled = n < 2;
    }

    function toggleChar(ch) {
      if (selectedSet.has(ch)) {
        selectedSet.delete(ch);
        manualMsg.textContent = "";
      } else {
        if (selectedSet.size >= 20) {
          manualMsg.textContent = "最多选 20 个字，不能再添加了。请先移除一些再试。";
          return;
        }
        selectedSet.add(ch);
        manualMsg.textContent = "";
      }
      refreshTags();
    }

    if (picker) {
      picker.addEventListener("click", (e) => {
        const btn = e.target.closest(".dictation-char-btn");
        if (btn) toggleChar(btn.dataset.char);
      });
    }
    tagList.addEventListener("click", (e) => {
      const rm = e.target.closest(".dictation-tag-remove");
      if (!rm) return;
      const idx = parseInt(rm.dataset.index, 10);
      const arr = Array.from(selectedSet);
      if (arr[idx] != null) selectedSet.delete(arr[idx]);
      refreshTags();
    });

    addBtn.addEventListener("click", () => {
      const val = manualInput.value.trim();
      if (!val) { manualMsg.textContent = "请先输入内容。"; return; }
      const chars = uniqueChineseCharacters(val);
      if (!chars.length) { manualMsg.textContent = "没有识别到汉字，请重新输入。"; return; }
      const remaining = 20 - selectedSet.size;
      if (remaining <= 0) {
        manualMsg.textContent = "已选满 20 个字，不能再添加了。请先移除一些再试。";
        return;
      }
      const already = chars.filter((ch) => selectedSet.has(ch)).length;
      const newOnes = chars.filter((ch) => !selectedSet.has(ch));
      const willAdd = newOnes.slice(0, remaining);
      willAdd.forEach((ch) => selectedSet.add(ch));
      const skipped = chars.length - willAdd.length - already;
      if (willAdd.length === 0) {
        manualMsg.textContent = already > 0
          ? "这些字已经添加过了。"
          : "已选满 20 个字，不能再添加了。";
      } else if (skipped > 0 || newOnes.length > remaining) {
        manualMsg.textContent = `已添加 ${willAdd.length} 个字，超出 20 的部分已忽略（最多 20 个不重复汉字）。`;
      } else if (already > 0) {
        manualMsg.textContent = `已添加 ${willAdd.length} 个字（${already} 个重复已跳过）。`;
      } else {
        manualMsg.textContent = `已添加 ${willAdd.length} 个字。`;
      }
      manualInput.value = "";
      refreshTags();
      manualInput.focus();
    });

    manualInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addBtn.click(); }
    });

    startBtn.addEventListener("click", () => {
      const arr = Array.from(selectedSet);
      if (arr.length < 2) {
        summary.textContent = "至少选择 2 个汉字才能开始听写。";
        return;
      }
      startDictationSession(arr.join(""));
    });
  }

  async function checkActiveDictation(container) {
    try {
      const r = await fetch("/api/dictation/session");
      if (!r.ok) return;
      const data = await r.json();
      if (!data.session) return;
      const s = data.session;
      const done = (s.attempts || []).length;
      const box = document.createElement("div");
      box.className = "dictation-resume-banner";
      const msg = document.createElement("p");
      msg.textContent = `有一次未完成的听写（${s.characters}），已完成 ${done}/${s.total_count}`;
      const resumeBtn = document.createElement("button");
      resumeBtn.type = "button";
      resumeBtn.className = "dictation-resume-btn";
      resumeBtn.textContent = "继续听写";
      resumeBtn.addEventListener("click", () => {
        dictationMode = "practice";
        dictationSession = s;
        dictationChars = Array.from(s.characters);
        dictationAttempts = s.attempts || [];
        const attemptedSet = new Set(dictationAttempts.map((a) => a.char_index));
        dictationCharIndex = 0;
        for (let i = 0; i < dictationChars.length; i++) {
          if (!attemptedSet.has(i)) { dictationCharIndex = i; break; }
          if (i === dictationChars.length - 1) dictationCharIndex = dictationChars.length;
        }
        renderDictationPractice();
      });
      box.append(msg, resumeBtn);
      container.innerHTML = "";
      container.append(box);
    } catch (_) { /* server off */ }
  }

  async function startDictationSession(chars) {
    try {
      const r = await fetch("/api/dictation/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ characters: chars })
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        summary.textContent = err.error || "创建听写失败，请确认服务已启动。";
        return;
      }
      const s = await r.json();
      dictationSession = { id: s.id, characters: s.characters, total_count: s.total_count };
      dictationChars = Array.from(s.characters);
      dictationAttempts = [];
      dictationCharIndex = 0;
      dictationMode = "practice";
      renderDictationPractice();
    } catch (_) {
      summary.textContent = "无法连接服务器，请确认本地服务已启动。";
    }
  }

  function renderDictationPractice() {
    cards.innerHTML = "";
    dictationRetryIndex = -1;
    dictationSubmitting = false;

    const allDone = dictationCharIndex >= dictationChars.length;
    if (allDone) { renderDictationSummary(); return; }

    const expected = dictationChars[dictationCharIndex];
    const panel = document.createElement("section");
    panel.className = "dictation-practice";

    const header = document.createElement("div");
    header.className = "dictation-practice-header";
    const prog = document.createElement("span");
    prog.className = "dictation-progress-label";
    prog.textContent = `第 ${dictationCharIndex + 1} 题 / 共 ${dictationChars.length} 题`;
    const quitBtn = document.createElement("button");
    quitBtn.type = "button";
    quitBtn.className = "dictation-quit-btn";
    quitBtn.textContent = "退出听写";
    quitBtn.addEventListener("click", () => { setFeature("dictation"); });
    header.append(prog, quitBtn);
    panel.append(header);

    const pBar = document.createElement("div");
    pBar.className = "dictation-progress-bar";
    const pFill = document.createElement("div");
    pFill.className = "dictation-progress-fill";
    pFill.style.width = `${((dictationCharIndex) / dictationChars.length) * 100}%`;
    pBar.append(pFill);
    panel.append(pBar);

    const audioSec = document.createElement("div");
    audioSec.className = "dictation-audio-section";
    const audioBtn = document.createElement("button");
    audioBtn.type = "button";
    audioBtn.className = "dictation-audio-btn";
    audioBtn.innerHTML = '<span class="dictation-audio-icon" aria-hidden="true">🔊</span><br><span>点击听读音</span>';
    if (!speechSupported) { audioBtn.disabled = true; audioBtn.title = "浏览器不支持语音"; }
    audioBtn.addEventListener("click", () => {
      if (audioBtn.disabled) return;
      speakText(expected, {
        rate: 0.7,
        onstart: () => { audioBtn.classList.add("is-speaking"); audioBtn.disabled = true; },
        onend: () => { audioBtn.classList.remove("is-speaking"); audioBtn.disabled = false; },
        onerror: () => { audioBtn.classList.remove("is-speaking"); audioBtn.disabled = false; }
      });
    });
    audioSec.append(audioBtn);
    panel.append(audioSec);

    const inputSec = document.createElement("div");
    inputSec.className = "dictation-input-section";
    const inputLabel = document.createElement("label");
    inputLabel.className = "dictation-input-label";
    inputLabel.textContent = "写出你听到的字：";
    const charInput = document.createElement("input");
    charInput.type = "text";
    charInput.className = "dictation-answer-input";
    charInput.placeholder = "输入你写的字";
    charInput.inputMode = "text";
    charInput.autocomplete = "off";
    charInput.maxLength = 4;
    const submitRow = document.createElement("div");
    submitRow.className = "dictation-submit-row";
    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "dictation-submit-btn";
    submitBtn.textContent = "提交";
    submitRow.append(submitBtn);
    inputSec.append(inputLabel, charInput, submitRow);
    panel.append(inputSec);

    const feedbackSec = document.createElement("div");
    feedbackSec.className = "dictation-feedback";
    feedbackSec.hidden = true;
    panel.append(feedbackSec);

    const msgLine = document.createElement("p");
    msgLine.className = "dictation-msg";
    inputSec.append(msgLine);

    cards.append(panel);
    summary.textContent = `听写中：第 ${dictationCharIndex + 1} / ${dictationChars.length} 题`;
    setTimeout(() => charInput.focus(), 100);

    async function submitAnswer() {
      if (dictationSubmitting) return;
      const val = charInput.value.trim();
      if (!val) { msgLine.textContent = "请先输入你写的字。"; charInput.focus(); return; }
      const cleaned = Array.from(val).filter(isChineseCharacter).join("");
      if (!cleaned) { msgLine.textContent = "请输入汉字。"; charInput.focus(); return; }
      const answer = cleaned[0];
      const idx = dictationCharIndex;
      const isRetry = dictationRetryIndex === idx;
      // `correct` always = first-attempt correctness (false on retry even if right now).
      const firstCorrect = !isRetry && answer === expected;
      // `corrected` = true only when a retry answer is right.
      const correctedNow = isRetry && answer === expected;

      dictationSubmitting = true;
      submitBtn.disabled = true;

      const body = {
        session_id: dictationSession.id,
        char_index: idx,
        expected_char: expected,
        user_input: answer,
        correct: firstCorrect,
        is_retry: isRetry,
        corrected: correctedNow
      };

      let apiOk = true;
      try {
        const r = await fetch("/api/dictation/attempt", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        if (!r.ok) apiOk = false;
      } catch (_) { apiOk = false; }

      // Update local attempts list (single entry per char_index).
      const existing = dictationAttempts.find((a) => a.char_index === idx);
      if (existing) {
        existing.user_input = answer;
        if (correctedNow) existing.corrected = 1;
      } else {
        dictationAttempts.push({
          char_index: idx,
          expected_char: expected,
          user_input: answer,
          correct: firstCorrect ? 1 : 0,
          corrected: 0
        });
      }

      if (!apiOk) {
        msgLine.textContent = "答案已暂存到本地，但未能保存到服务器。";
      }

      // Display feedback: "got it right" shown when first-try correct OR corrected-on-retry.
      showFeedback(firstCorrect || correctedNow, expected, answer, idx, correctedNow, firstCorrect);
    }

    function showFeedback(displayRight, exp, ans, idx, isCorrectedRetry, isFirstTryRight) {
      feedbackSec.hidden = false;
      feedbackSec.innerHTML = "";
      inputSec.querySelector(".dictation-answer-input").disabled = true;

      const reveal = document.createElement("div");
      reveal.className = "dictation-reveal";
      const rvLabel = document.createElement("span");
      rvLabel.className = "dictation-reveal-label";
      rvLabel.textContent = "正确答案：";
      const rvChar = document.createElement("span");
      rvChar.className = "dictation-reveal-char";
      rvChar.textContent = exp;
      reveal.append(rvLabel, rvChar);

      const statusMsg = document.createElement("p");
      if (isFirstTryRight) {
        feedbackSec.classList.add("is-correct");
        feedbackSec.classList.remove("is-wrong");
        statusMsg.className = "dictation-status correct";
        statusMsg.textContent = "✅ 答对了！你真棒！";
      } else if (isCorrectedRetry) {
        feedbackSec.classList.add("is-correct");
        feedbackSec.classList.remove("is-wrong");
        statusMsg.className = "dictation-status correct";
        statusMsg.textContent = "✅ 改正成功！这道题仍算第一次的错误哦。";
      } else {
        feedbackSec.classList.add("is-wrong");
        feedbackSec.classList.remove("is-correct");
        statusMsg.className = "dictation-status wrong";
        statusMsg.textContent = "❌ 答错了，你写的是：" + ans;
      }
      feedbackSec.append(reveal, statusMsg);

      const actions = document.createElement("div");
      actions.className = "dictation-feedback-actions";

      // Offer retry only when the current answer is still wrong.
      if (!displayRight) {
        const retryBtn = document.createElement("button");
        retryBtn.type = "button";
        retryBtn.className = "dictation-retry-btn";
        retryBtn.textContent = "改正";
        retryBtn.addEventListener("click", () => {
          dictationRetryIndex = idx;
          inputSec.querySelector(".dictation-answer-input").disabled = false;
          inputSec.querySelector(".dictation-answer-input").value = "";
          inputSec.querySelector(".dictation-answer-input").focus();
          msgLine.textContent = "再试一次，写出正确的字：";
          feedbackSec.hidden = true;
          submitBtn.disabled = false;
          submitBtn.textContent = "再次提交";
          dictationSubmitting = false;
        });
        actions.append(retryBtn);
      }

      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "dictation-next-btn";
      nextBtn.textContent = dictationCharIndex >= dictationChars.length - 1 ? "查看结果" : "下一题";
      nextBtn.addEventListener("click", () => {
        dictationCharIndex++;
        renderDictationPractice();
      });
      actions.append(nextBtn);
      feedbackSec.append(actions);
    }

    submitBtn.addEventListener("click", submitAnswer);
    charInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); submitAnswer(); }
    });
  }

  async function renderDictationSummary() {
    cards.innerHTML = "";
    const session = dictationSession;
    if (!session) { renderDictationSetup(); return; }

    const total = dictationChars.length;
    // Correct count = first-attempt correct only (correct===1).
    const rightCount = dictationAttempts.filter((a) => a.correct === 1).length;
    // Wrong items = first-attempt wrong (correct===0), even if corrected on retry.
    const wrongItems = dictationAttempts.filter((a) => a.correct === 0);
    const correctedCount = wrongItems.filter((a) => a.corrected === 1).length;

    const panel = document.createElement("section");
    panel.className = "dictation-summary";

    const title = document.createElement("h3");
    title.className = "dictation-summary-title";
    title.textContent = "🎉 听写完成！";
    panel.append(title);

    const stats = document.createElement("div");
    stats.className = "dictation-stats";

    const statTotal = document.createElement("div");
    statTotal.className = "dictation-stat";
    statTotal.innerHTML = '<span class="dictation-stat-value">' + total + '</span><span class="dictation-stat-label">总题数</span>';

    const statRight = document.createElement("div");
    statRight.className = "dictation-stat dictation-stat-correct";
    statRight.innerHTML = '<span class="dictation-stat-value">' + rightCount + '</span><span class="dictation-stat-label">第一次就答对</span>';

    const statWrong = document.createElement("div");
    statWrong.className = "dictation-stat dictation-stat-wrong";
    const wrongHint = correctedCount > 0 ? `（${correctedCount} 个后改对）` : "";
    statWrong.innerHTML = '<span class="dictation-stat-value">' + wrongItems.length + '</span><span class="dictation-stat-label">第一次答错' + wrongHint + '</span>';

    const pct = total > 0 ? Math.round((rightCount / total) * 100) : 0;
    const statRate = document.createElement("div");
    statRate.className = "dictation-stat";
    statRate.innerHTML = '<span class="dictation-stat-value">' + pct + '%</span><span class="dictation-stat-label">首次正确率</span>';

    stats.append(statTotal, statRight, statWrong, statRate);
    panel.append(stats);

    if (wrongItems.length > 0) {
      const wrongSec = document.createElement("div");
      wrongSec.className = "dictation-wrong-section";
      const wrongTitle = document.createElement("h4");
      wrongTitle.textContent = "第一次写错的字：";
      wrongSec.append(wrongTitle);
      const wrongList = document.createElement("div");
      wrongList.className = "dictation-wrong-list";
      wrongItems.forEach((a) => {
        const item = document.createElement("div");
        item.className = "dictation-wrong-item";
        const right = document.createElement("span");
        right.className = "dictation-wrong-correct";
        right.textContent = a.expected_char;
        item.append(right);
        if (a.corrected === 1) {
          const tag = document.createElement("span");
          tag.className = "dictation-wrong-tag";
          tag.textContent = "已改对";
          item.append(tag);
        } else {
          const wrote = document.createElement("span");
          wrote.className = "dictation-wrong-user";
          wrote.textContent = "(你写了：" + (a.user_input || "—") + ")";
          item.append(wrote);
        }
        wrongList.append(item);
      });
      wrongSec.append(wrongList);
      panel.append(wrongSec);
    } else {
      const allRight = document.createElement("p");
      allRight.className = "dictation-all-correct";
      allRight.textContent = "全部答对！没有错字！太厉害了！";
      panel.append(allRight);
    }

    const details = document.createElement("div");
    details.className = "dictation-detail-section";
    const detHead = document.createElement("h4");
    detHead.textContent = "全部题目详情";
    details.append(detHead);
    const detList = document.createElement("div");
    detList.className = "dictation-detail-list";
    dictationChars.forEach((ch, i) => {
      const att = dictationAttempts.find((a) => a.char_index === i);
      const row = document.createElement("div");
      row.className = "dictation-detail-row";
      const chSpan = document.createElement("span");
      chSpan.className = "dictation-detail-char";
      chSpan.textContent = ch;
      const badge = document.createElement("span");
      if (!att) {
        badge.className = "dictation-detail-badge skipped";
        badge.textContent = "未答";
      } else if (att.correct === 1) {
        badge.className = "dictation-detail-badge correct";
        badge.textContent = "首次正确";
      } else if (att.corrected === 1) {
        badge.className = "dictation-detail-badge corrected";
        badge.textContent = "改对（首次错误）";
      } else {
        badge.className = "dictation-detail-badge wrong";
        badge.textContent = "错误（" + (att.user_input || "—") + "）";
      }
      row.append(chSpan, badge);
      detList.append(row);
    });
    details.append(detList);
    panel.append(details);

    const actions = document.createElement("div");
    actions.className = "dictation-summary-actions";

    // Always show retry button when there are wrong items (including 1-char retry).
    if (wrongItems.length > 0) {
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "dictation-retry-all-btn";
      retryBtn.textContent = wrongItems.length === 1
        ? "错字再听写一遍"
        : `错字再听写一遍（${wrongItems.length} 个）`;
      retryBtn.addEventListener("click", () => {
        const wrongChars = wrongItems.map((a) => a.expected_char).join("");
        startDictationSession(wrongChars);
      });
      actions.append(retryBtn);
    }

    const newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "dictation-new-btn";
    newBtn.textContent = "新的听写";
    newBtn.addEventListener("click", () => {
      dictationMode = "setup";
      dictationSession = null;
      renderDictationSetup();
    });
    actions.append(newBtn);
    panel.append(actions);

    cards.append(panel);

    // Render past dictation results below the summary.
    const resultsSlot = document.createElement("div");
    resultsSlot.className = "dictation-past-results";
    cards.append(resultsSlot);
    await loadDictationResults();

    summary.textContent = `听写完成：共 ${total} 题，首次答对 ${rightCount} 题，首次正确率 ${pct}%。`;
  }

  async function loadDictationResults() {
    try {
      const r = await fetch("/api/dictation/results?limit=20");
      if (!r.ok) return;
      const data = await r.json();
      pastDictationResults = data.items || [];
      renderPastResults();
    } catch (_) { /* server off */ }
  }

  function renderPastResults() {
    const slot = cards.querySelector(".dictation-past-results");
    if (!slot) return;
    slot.innerHTML = "";
    if (!pastDictationResults.length) return;

    const sec = document.createElement("div");
    sec.className = "dictation-past-section";
    const title = document.createElement("h4");
    title.textContent = "历史听写记录";
    sec.append(title);

    const list = document.createElement("div");
    list.className = "dictation-past-list";
    pastDictationResults.forEach((item) => {
      const row = document.createElement("div");
      row.className = "dictation-past-row";
      const left = document.createElement("div");
      left.className = "dictation-past-info";
      const chars = document.createElement("span");
      chars.className = "dictation-past-chars";
      chars.textContent = item.characters;
      const meta = document.createElement("span");
      meta.className = "dictation-past-meta";
      const pct = item.total_count > 0 ? Math.round((item.correct_count / item.total_count) * 100) : 0;
      meta.textContent = `${item.created_at || ""} · ${item.correct_count}/${item.total_count} 正确 · 正确率 ${pct}%`;
      left.append(chars, meta);
      row.append(left);
      if (item.wrong_chars && item.wrong_chars.length > 0) {
        const wrong = document.createElement("span");
        wrong.className = "dictation-past-wrong";
        wrong.textContent = "错字：" + item.wrong_chars.join("");
        row.append(wrong);
      }
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "dictation-past-delete";
      delBtn.textContent = "删除";
      delBtn.addEventListener("click", async () => {
        try {
          await fetch("/api/dictation/session?id=" + item.id, { method: "DELETE" });
          row.remove();
          pastDictationResults = pastDictationResults.filter((r) => r.id !== item.id);
          if (!pastDictationResults.length) slot.innerHTML = "";
        } catch (_) { /* fail silently */ }
      });
      row.append(delBtn);
      list.append(row);
    });
    sec.append(list);
    slot.append(sec);
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
})();
