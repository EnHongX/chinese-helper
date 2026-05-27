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
    history: {
      title: "学习记录",
      description: "查看本地查询历史，可单选或多选删除记录。",
      placeholder: "",
      help: "点击记录内容会自动切换到对应功能并回填查询。",
      resultsTitle: "学习记录"
    },
    dictation: {
      title: "听写复习",
      description: "选字开始听写，每次只出一个字，听读音写出来。",
      placeholder: "",
      help: "可以从已查过的字里挑选，也可以自己输入，最少2个、最多20个。",
      resultsTitle: "听写复习"
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
    if (currentFeature === "history") {
      renderHistoryPage();
      return;
    }

    if (currentFeature === "dictation") {
      renderDictationPage();
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
      ["sentences", "造句"]
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

  // Auto-resume active dictation session on page load
  (async () => {
    try {
      const active = await apiFetch("/api/dictation/active");
      if (active && active.status === "active") {
        const data = await apiFetch(`/api/dictation/session?id=${active.id}`);
        dictationState.session = data.session;
        dictationState.items = data.items;
        dictationState.currentIndex = data.session.current_index;
        setFeature("dictation");
      }
    } catch (e) {
      // no active session, stay on default view
    }
  })();

  // ==================== 听写功能 ====================

  let dictationState = {
    session: null,
    items: [],
    currentIndex: 0,
    submitting: false
  };

  async function apiFetch(url, options) {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `请求失败 (${resp.status})`);
    }
    return resp.json();
  }

  function showDictationToast(message, type) {
    const existing = document.querySelector(".dictation-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = "dictation-toast" + (type ? ` dictation-toast-${type}` : "");
    toast.textContent = message;
    document.body.append(toast);
    setTimeout(() => toast.classList.add("show"), 10);
    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, 2500);
  }

  async function renderDictationPage() {
    hidePager();
    currentCharacters = [];
    currentCharIndex = 0;
    cards.innerHTML = "";
    searchPanel.hidden = true;

    // If state already loaded (e.g. from auto-resume), skip fetch
    if (dictationState.session && dictationState.session.status === "active" && dictationState.items.length) {
      await renderDictationSession();
      return;
    }

    try {
      const active = await apiFetch("/api/dictation/active");
      if (active && active.status === "active") {
        const data = await apiFetch(`/api/dictation/session?id=${active.id}`);
        dictationState.session = data.session;
        dictationState.items = data.items;
        dictationState.currentIndex = data.session.current_index;
        await renderDictationSession();
        return;
      }
    } catch (e) {
      // no active session, proceed to setup
    }
    await renderDictationSetup();
  }

  async function renderDictationSetup() {
    cards.innerHTML = "";
    summary.textContent = "选择要听写的汉字";

    const panel = document.createElement("section");
    panel.className = "dictation-panel";

    // --- Chip area from history ---
    const chipSection = document.createElement("div");
    chipSection.className = "dictation-chip-section";

    const chipTitle = document.createElement("h3");
    chipTitle.textContent = "从已学汉字中挑选";
    chipSection.append(chipTitle);

    const chipArea = document.createElement("div");
    chipArea.className = "dictation-chip-area";

    // Load history characters for chips
    let historyChars = [];
    let historyLoadError = false;
    try {
      const resp = await apiFetch("/api/history?limit=50");
      const items = resp.items || [];
      const seen = new Set();
      items.forEach((item) => {
        if (item.characters) {
          Array.from(item.characters).forEach((ch) => {
            if (isChineseCharacter(ch) && !seen.has(ch)) {
              seen.add(ch);
              historyChars.push(ch);
            }
          });
        }
      });
    } catch (e) {
      historyLoadError = true;
    }

    if (historyLoadError) {
      const errMsg = document.createElement("p");
      errMsg.className = "dictation-no-chars dictation-error-msg";
      errMsg.textContent = "无法加载已学汉字，请确认服务已启动。";
      chipArea.append(errMsg);
    } else if (historyChars.length === 0) {
      const noChars = document.createElement("p");
      noChars.className = "dictation-no-chars";
      noChars.textContent = "还没有查过字，请先去「汉字」功能查几个字再来～";
      chipArea.append(noChars);
    } else {
      historyChars.forEach((ch) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "dictation-chip";
        chip.textContent = ch;
        chip.dataset.char = ch;
        chip.addEventListener("click", () => {
          chip.classList.toggle("selected");
          updateSelectedDisplay();
        });
        chipArea.append(chip);
      });
    }

    chipSection.append(chipArea);
    panel.append(chipSection);

    // --- Selected display ---
    const selectedSection = document.createElement("div");
    selectedSection.className = "dictation-selected-section";

    const selectedLabel = document.createElement("p");
    selectedLabel.className = "dictation-selected-label";
    selectedLabel.textContent = "已选：0 个字";

    const selectedChars = document.createElement("div");
    selectedChars.className = "dictation-selected-chars";

    selectedSection.append(selectedLabel, selectedChars);
    panel.append(selectedSection);

    // --- Manual input ---
    const inputSection = document.createElement("div");
    inputSection.className = "dictation-input-section";

    const inputLabel = document.createElement("p");
    inputLabel.textContent = "也可以直接输入要听写的字：";

    const manualInput = document.createElement("input");
    manualInput.type = "text";
    manualInput.className = "dictation-manual-input";
    manualInput.placeholder = "例如：春夏秋冬";
    manualInput.setAttribute("aria-label", "输入要听写的汉字");

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "dictation-add-btn";
    addBtn.textContent = "加入";

    inputSection.append(inputLabel, manualInput, addBtn);
    panel.append(inputSection);

    // --- Start button ---
    const startBtn = document.createElement("button");
    startBtn.type = "button";
    startBtn.className = "dictation-start-btn";
    startBtn.textContent = "开始听写";
    panel.append(startBtn);

    cards.append(panel);

    // Show past dictation history below setup
    const historySlot = document.createElement("section");
    historySlot.className = "dictation-history-section";
    cards.append(historySlot);
    loadDictationResultsIntoSlot(historySlot);

    function getSelectedChars() {
      const selected = Array.from(chipArea.querySelectorAll(".dictation-chip.selected"));
      const seen = new Set();
      const chars = [];
      selected.forEach((chip) => {
        const ch = chip.dataset.char;
        if (!seen.has(ch)) {
          seen.add(ch);
          chars.push(ch);
        }
      });
      // Also add from manual display
      Array.from(selectedChars.querySelectorAll(".dictation-selected-tag")).forEach((tag) => {
        const ch = tag.dataset.char;
        if (!seen.has(ch)) {
          seen.add(ch);
          chars.push(ch);
        }
      });
      return chars;
    }

    function updateSelectedDisplay() {
      const chars = getSelectedChars();
      selectedLabel.textContent = `已选：${chars.length} 个字`;
      selectedChars.innerHTML = "";
      chars.forEach((ch) => {
        const tag = document.createElement("span");
        tag.className = "dictation-selected-tag";
        tag.textContent = ch;
        tag.dataset.char = ch;
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "dictation-remove-tag";
        removeBtn.textContent = "×";
        removeBtn.setAttribute("aria-label", `移除 ${ch}`);
        removeBtn.addEventListener("click", () => {
          // Deselect chip if exists
          const chip = chipArea.querySelector(`[data-char="${ch}"]`);
          if (chip) chip.classList.remove("selected");
          tag.remove();
          updateSelectedDisplay();
        });
        tag.append(removeBtn);
        selectedChars.append(tag);
      });
    }

    addBtn.addEventListener("click", () => {
      const raw = manualInput.value.trim();
      const newChars = uniqueChineseCharacters(raw);
      if (!newChars.length) {
        showDictationToast("没有识别到汉字", "warn");
        return;
      }
      const currentChars = getSelectedChars();
      const seen = new Set(currentChars);
      let added = 0;
      newChars.forEach((ch) => {
        if (!seen.has(ch)) {
          seen.add(ch);
          const tag = document.createElement("span");
          tag.className = "dictation-selected-tag";
          tag.textContent = ch;
          tag.dataset.char = ch;
          const removeBtn = document.createElement("button");
          removeBtn.type = "button";
          removeBtn.className = "dictation-remove-tag";
          removeBtn.textContent = "×";
          removeBtn.setAttribute("aria-label", `移除 ${ch}`);
          removeBtn.addEventListener("click", () => {
            const chip = chipArea.querySelector(`[data-char="${ch}"]`);
            if (chip) chip.classList.remove("selected");
            tag.remove();
            updateSelectedDisplay();
          });
          tag.append(removeBtn);
          selectedChars.append(tag);
          added++;
        }
      });
      manualInput.value = "";
      if (added > 0) {
        showDictationToast(`加入了 ${added} 个新字`, "ok");
      } else {
        showDictationToast("这些字已经选过了", "warn");
      }
      updateSelectedDisplay();
    });

    startBtn.addEventListener("click", async () => {
      const chars = getSelectedChars();
      if (chars.length < 2) {
        showDictationToast("至少需要选2个汉字才能开始听写", "warn");
        return;
      }
      if (chars.length > 20) {
        showDictationToast("最多只能选20个汉字", "warn");
        return;
      }
      startBtn.disabled = true;
      startBtn.textContent = "正在创建...";
      try {
        const data = await apiFetch("/api/dictation/session", {
          method: "POST",
          body: JSON.stringify({ characters: chars })
        });
        dictationState.session = data.session;
        dictationState.items = data.items;
        dictationState.currentIndex = 0;
        await renderDictationSession();
      } catch (e) {
        showDictationToast(e.message || "创建听写失败，请确认服务已启动", "error");
        startBtn.disabled = false;
        startBtn.textContent = "开始听写";
      }
    });
  }

  async function renderDictationSession() {
    const { session, items, currentIndex: idx } = dictationState;
    if (!session || !items.length) return;

    // Find next item: skip answered-correct items, but show wrong-uncorrected items for retry
    let nextIndex = idx;
    while (nextIndex < items.length) {
      const it = items[nextIndex];
      const done = (it.correct && !it.corrected) || it.corrected;
      if (!done) break;
      nextIndex++;
    }
    if (nextIndex >= items.length) {
      await renderDictationSummary();
      return;
    }
    dictationState.currentIndex = nextIndex;

    // Check if this item was already answered wrong (refresh resume case)
    const currentItem = items[nextIndex];
    const isResumingWrong = currentItem.attempt_count > 0 && !currentItem.correct && !currentItem.corrected;

    cards.innerHTML = "";
    summary.textContent = `听写进行中 · 第 ${nextIndex + 1} / ${items.length} 题`;

    const panel = document.createElement("section");
    panel.className = "dictation-session-panel";

    // Progress bar
    const progressWrap = document.createElement("div");
    progressWrap.className = "dictation-progress";
    const answered = items.filter((i) => i.attempt_count > 0).length;
    const pct = Math.round((answered / items.length) * 100);
    const bar = document.createElement("div");
    bar.className = "dictation-progress-bar";
    bar.style.width = pct + "%";
    progressWrap.append(bar);
    panel.append(progressWrap);

    // Character display
    const charShow = document.createElement("div");
    charShow.className = "dictation-char-show";

    const charBig = document.createElement("div");
    charBig.className = "dictation-char-big";
    charBig.textContent = "？";
    charBig.id = "dictation-char-display";

    const playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "dictation-play-btn";
    playBtn.innerHTML = '<span class="speak-icon" aria-hidden="true">🔊</span>';
    playBtn.setAttribute("aria-label", "听读音");
    playBtn.addEventListener("click", () => {
      speakText(items[nextIndex].character, {
        rate: 0.7,
        onstart: () => { playBtn.classList.add("is-speaking"); },
        onend: () => { playBtn.classList.remove("is-speaking"); },
        onerror: () => { playBtn.classList.remove("is-speaking"); }
      });
    });

    charShow.append(charBig, playBtn);
    panel.append(charShow);

    // Hint button
    const hintArea = document.createElement("div");
    hintArea.className = "dictation-hint-area";
    const hintBtn = document.createElement("button");
    hintBtn.type = "button";
    hintBtn.className = "dictation-hint-btn";
    hintBtn.textContent = "看提示";
    hintBtn.addEventListener("click", () => {
      const ch = items[nextIndex].character;
      hintBtn.disabled = true;
      hintBtn.textContent = "加载中…";
      ensureShardsForChars([ch]).then(() => {
        const entry = shardChar(ch);
        if (entry && entry.pinyin && entry.pinyin !== "暂无") {
          hintBtn.textContent = `提示：拼音 ${entry.pinyin}`;
        } else if (entry && entry.radical && entry.radical !== "暂无") {
          hintBtn.textContent = `提示：部首是「${entry.radical}」`;
        } else {
          hintBtn.textContent = "提示：暂无更多提示数据";
        }
        hintBtn.disabled = false;
      });
    });
    hintArea.append(hintBtn);
    panel.append(hintArea);

    // Answer input
    const answerArea = document.createElement("div");
    answerArea.className = "dictation-answer-area";

    const answerInput = document.createElement("input");
    answerInput.type = "text";
    answerInput.className = "dictation-answer-input";
    answerInput.placeholder = "写出这个字";
    answerInput.setAttribute("aria-label", "输入答案");
    answerInput.maxLength = 1;

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "dictation-submit-btn";
    submitBtn.textContent = "提交";

    const feedback = document.createElement("div");
    feedback.className = "dictation-feedback";

    answerArea.append(answerInput, submitBtn, feedback);
    panel.append(answerArea);

    cards.append(panel);
    answerInput.focus();

    // If resuming a wrong answer, show the correct answer + retry UI immediately
    if (isResumingWrong) {
      const correct = currentItem.character;
      charBig.textContent = correct;
      charBig.classList.add("wrong");
      feedback.className = "dictation-feedback dictation-feedback-wrong";
      feedback.textContent = `✗ 之前写错了，正确答案是「${correct}」，请再写一遍`;
      submitBtn.hidden = true;
      answerInput.hidden = true;

      const retryArea = document.createElement("div");
      retryArea.className = "dictation-retry-area";
      const retryLabel = document.createElement("p");
      retryLabel.textContent = "再试一次（写对才能进入下一题）：";
      const retryInput = document.createElement("input");
      retryInput.type = "text";
      retryInput.className = "dictation-answer-input";
      retryInput.placeholder = "重新写一遍";
      retryInput.maxLength = 1;
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "dictation-submit-btn dictation-retry-btn";
      retryBtn.textContent = "提交";

      retryArea.append(retryLabel, retryInput, retryBtn);
      answerArea.append(retryArea);
      retryInput.focus();

      function handleResumeRetry() {
        const retryAnswer = retryInput.value.trim();
        if (!retryAnswer) {
          showDictationToast("请写出你的答案", "warn");
          return;
        }
        if (retryAnswer !== correct) {
          showDictationToast("还是不对哦，再看看正确答案，再写一遍", "warn");
          retryInput.value = "";
          retryInput.focus();
          return;
        }
        retryBtn.disabled = true;
        retryInput.disabled = true;
        feedback.className = "dictation-feedback dictation-feedback-corrected";
        feedback.textContent = "✓ 这次写对了！继续加油！";
        apiFetch("/api/dictation/attempt", {
          method: "POST",
          body: JSON.stringify({
            session_id: session.id,
            character: correct,
            correct: false,
            corrected: true
          })
        }).then((result) => {
          dictationState.session = result.session;
          dictationState.items = result.items;
        }).catch(() => {});
        setTimeout(() => {
          dictationState.currentIndex = nextIndex + 1;
          dictationState.submitting = false;
          renderDictationSession();
        }, 1200);
      }

      retryBtn.addEventListener("click", handleResumeRetry);
      retryInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); handleResumeRetry(); }
      });
    }

    // Auto-play sound
    setTimeout(() => {
      speakText(items[nextIndex].character, {
        rate: 0.7,
        onstart: () => { playBtn.classList.add("is-speaking"); },
        onend: () => { playBtn.classList.remove("is-speaking"); },
        onerror: () => { playBtn.classList.remove("is-speaking"); }
      });
    }, 300);

    async function submitAnswer() {
      const answer = answerInput.value.trim();
      if (!answer) {
        showDictationToast("请先写出你的答案", "warn");
        return;
      }
      if (dictationState.submitting) return;
      dictationState.submitting = true;
      submitBtn.disabled = true;

      const correct = items[nextIndex].character;
      const isCorrect = answer === correct;

      // Show character
      charBig.textContent = correct;
      charBig.classList.add(isCorrect ? "correct" : "wrong");

      if (isCorrect) {
        feedback.className = "dictation-feedback dictation-feedback-correct";
        feedback.textContent = "✓ 写对了！真棒！";
        try {
          await apiFetch("/api/dictation/attempt", {
            method: "POST",
            body: JSON.stringify({
              session_id: session.id,
              character: correct,
              correct: true,
              corrected: false
            })
          });
        } catch (e) { /* silently continue */ }
      } else {
        feedback.className = "dictation-feedback dictation-feedback-wrong";
        feedback.textContent = `✗ 写错了，正确答案是「${correct}」，请再写一遍`;

        // Immediately save the wrong attempt so refresh doesn't lose it
        try {
          const result = await apiFetch("/api/dictation/attempt", {
            method: "POST",
            body: JSON.stringify({
              session_id: session.id,
              character: correct,
              correct: false,
              corrected: false
            })
          });
          dictationState.session = result.session;
          dictationState.items = result.items;
        } catch (e) { /* continue */ }

        // Show retry input — must keep trying until correct
        const retryArea = document.createElement("div");
        retryArea.className = "dictation-retry-area";
        const retryLabel = document.createElement("p");
        retryLabel.textContent = "再试一次（写对才能进入下一题）：";
        const retryInput = document.createElement("input");
        retryInput.type = "text";
        retryInput.className = "dictation-answer-input";
        retryInput.placeholder = "重新写一遍";
        retryInput.maxLength = 1;
        const retryBtn = document.createElement("button");
        retryBtn.type = "button";
        retryBtn.className = "dictation-submit-btn dictation-retry-btn";
        retryBtn.textContent = "提交";

        retryArea.append(retryLabel, retryInput, retryBtn);
        answerArea.append(retryArea);

        retryInput.focus();

        function handleRetry() {
          const retryAnswer = retryInput.value.trim();
          if (!retryAnswer) {
            showDictationToast("请写出你的答案", "warn");
            return;
          }
          const isRetryCorrect = retryAnswer === correct;
          if (!isRetryCorrect) {
            showDictationToast("还是不对哦，再看看正确答案，再写一遍", "warn");
            retryInput.value = "";
            retryInput.focus();
            return;
          }
          // Correct on retry
          retryBtn.disabled = true;
          retryInput.disabled = true;
          feedback.className = "dictation-feedback dictation-feedback-corrected";
          feedback.textContent = "✓ 这次写对了！继续加油！";
          // Submit corrected attempt
          apiFetch("/api/dictation/attempt", {
            method: "POST",
            body: JSON.stringify({
              session_id: session.id,
              character: correct,
              correct: false,
              corrected: true
            })
          }).then((result) => {
            dictationState.session = result.session;
            dictationState.items = result.items;
          }).catch(() => {});
          setTimeout(() => {
            dictationState.currentIndex = nextIndex + 1;
            dictationState.submitting = false;
            renderDictationSession();
          }, 1200);
        }

        retryBtn.addEventListener("click", handleRetry);
        retryInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleRetry();
          }
        });
        return; // Don't auto-advance on wrong answer
      }

      // Auto advance on correct
      setTimeout(() => {
        dictationState.currentIndex = nextIndex + 1;
        dictationState.submitting = false;
        renderDictationSession();
      }, 1200);
    }

    submitBtn.addEventListener("click", submitAnswer);
    answerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitAnswer();
      }
    });
  }

  async function renderDictationSummary() {
    const { session, items } = dictationState;
    if (!session) return;

    cards.innerHTML = "";
    summary.textContent = "听写完成！";

    // Refresh session data from server
    try {
      const data = await apiFetch(`/api/dictation/session?id=${session.id}`);
      dictationState.session = data.session;
      dictationState.items = data.items;
    } catch (e) { /* use local state */ }

    const s = dictationState.session;
    const allItems = dictationState.items;
    const total = s.total;
    const correctCount = s.correct_count;
    const accuracy = total > 0 ? Math.round((correctCount / total) * 100) : 0;
    const wrongItems = allItems.filter((i) => !i.correct);

    const panel = document.createElement("section");
    panel.className = "dictation-summary-panel";

    // Score card
    const scoreCard = document.createElement("div");
    scoreCard.className = "dictation-score-card";

    const scoreBig = document.createElement("div");
    scoreBig.className = "dictation-score-big";
    scoreBig.textContent = accuracy + "%";

    const scoreDetail = document.createElement("div");
    scoreDetail.className = "dictation-score-detail";
    scoreDetail.textContent = `共 ${total} 题，答对 ${correctCount} 题`;

    scoreCard.append(scoreBig, scoreDetail);
    panel.append(scoreCard);

    if (wrongItems.length === 0) {
      const allCorrect = document.createElement("div");
      allCorrect.className = "dictation-all-correct";
      allCorrect.textContent = "全部答对！没有错字！太厉害了！";
      panel.append(allCorrect);
    } else {
      // Wrong chars display
      const wrongSection = document.createElement("div");
      wrongSection.className = "dictation-wrong-section";

      const wrongTitle = document.createElement("h3");
      wrongTitle.textContent = "写错的字";
      wrongSection.append(wrongTitle);

      const wrongList = document.createElement("div");
      wrongList.className = "dictation-wrong-list";
      wrongItems.forEach((item) => {
        const tag = document.createElement("span");
        tag.className = "dictation-wrong-tag";
        tag.textContent = item.character;
        wrongList.append(tag);
      });
      wrongSection.append(wrongList);
      panel.append(wrongSection);

      // Retry wrong button
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "dictation-retry-wrong-btn";
      retryBtn.textContent = "把错字再听写一遍";
      retryBtn.addEventListener("click", async () => {
        const wrongChars = wrongItems.map((i) => i.character);
        try {
          const data = await apiFetch("/api/dictation/session", {
            method: "POST",
            body: JSON.stringify({ characters: wrongChars, retry: true })
          });
          dictationState.session = data.session;
          dictationState.items = data.items;
          dictationState.currentIndex = 0;
          renderDictationSession();
        } catch (e) {
          showDictationToast(e.message || "创建重听失败", "error");
        }
      });
      panel.append(retryBtn);
    }

    // New dictation button
    const newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "dictation-new-btn";
    newBtn.textContent = "开始新的听写";
    newBtn.addEventListener("click", () => {
      dictationState = { session: null, items: [], currentIndex: 0, submitting: false };
      renderDictationSetup();
    });
    panel.append(newBtn);

    // History section
    const resultsSlot = document.createElement("div");
    resultsSlot.className = "dictation-results-slot";
    panel.append(resultsSlot);

    cards.append(panel);

    // Load history in background
    loadDictationResults(resultsSlot);
  }

  async function loadDictationResultsIntoSlot(container) {
    try {
      const data = await apiFetch("/api/dictation/history");
      const items = data.items || [];
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "dictation-history-empty";
        empty.textContent = "暂无听写记录。";
        container.append(empty);
        return;
      }

      const title = document.createElement("h3");
      title.className = "dictation-history-title";
      title.textContent = "听写记录";
      container.append(title);

      const list = document.createElement("div");
      list.className = "dictation-history-list";

      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "dictation-history-row";

        const accuracy = item.total > 0 ? Math.round((item.correct_count / item.total) * 100) : 0;
        const wrong = item.wrong_chars || "";

        const meta = document.createElement("span");
        meta.className = "dictation-history-meta";
        meta.textContent = `${item.created_at || ""} · 对${item.correct_count}/${item.total} · ${accuracy}%`;

        const chars = document.createElement("span");
        chars.className = "dictation-history-chars";
        chars.textContent = wrong ? `错字：${wrong}` : "全部答对";

        row.append(meta, chars);
        list.append(row);
      });

      container.append(list);
    } catch (e) {
      const empty = document.createElement("p");
      empty.className = "dictation-history-empty";
      empty.textContent = "无法加载听写记录，请确认服务已启动。";
      container.append(empty);
    }
  }

  async function loadDictationResults(container) {
    try {
      const data = await apiFetch("/api/dictation/history");
      const items = data.items || [];
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "dictation-history-empty";
        empty.textContent = "暂无听写记录。";
        container.append(empty);
        return;
      }

      const title = document.createElement("h3");
      title.className = "dictation-history-title";
      title.textContent = "听写记录";
      container.append(title);

      const list = document.createElement("div");
      list.className = "dictation-history-list";

      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "dictation-history-row";

        const accuracy = item.total > 0 ? Math.round((item.correct_count / item.total) * 100) : 0;
        const wrong = item.wrong_chars || "";

        const meta = document.createElement("span");
        meta.className = "dictation-history-meta";
        meta.textContent = `${item.created_at || ""} · 对${item.correct_count}/${item.total} · ${accuracy}%`;

        const chars = document.createElement("span");
        chars.className = "dictation-history-chars";
        chars.textContent = wrong ? `错字：${wrong}` : "全部答对";

        row.append(meta, chars);
        list.append(row);
      });

      container.append(list);
    } catch (e) {
      const empty = document.createElement("p");
      empty.className = "dictation-history-empty";
      empty.textContent = "无法加载听写记录，请确认服务已启动。";
      container.append(empty);
    }
  }
})();
