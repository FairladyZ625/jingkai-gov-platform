// 最小 DOM 桩：只实现 admin-ai.js 用到的节点、属性和事件，供 Node 行为测试使用。
class TextNode {
  constructor(text) {
    this.nodeType = 3;
    this.parentNode = null;
    this._text = String(text);
  }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value); }
}

class ClassList {
  constructor(node) { this.node = node; }
  values() { return String(this.node.className || '').split(/\s+/).filter(Boolean); }
  contains(name) { return this.values().includes(name); }
  add(...names) { this.node.className = [...new Set([...this.values(), ...names])].join(' '); }
  remove(...names) { this.node.className = this.values().filter((item) => !names.includes(item)).join(' '); }
  toggle(name, force) {
    const has = this.contains(name);
    const next = force === undefined ? !has : Boolean(force);
    if (next) this.add(name); else this.remove(name);
    return next;
  }
  toString() { return this.values().join(' '); }
}

class Element {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.className = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.selected = false;
    this.classList = new ClassList(this);
  }
  get childNodes() { return this.children; }
  get textContent() { return this.children.map((child) => child.textContent).join(''); }
  set textContent(value) {
    this.children = [];
    if (value !== '') this.append(new TextNode(value));
  }
  append(...nodes) {
    for (const node of nodes.flat(Infinity)) {
      if (node == null || node === false) continue;
      const child = node instanceof TextNode || node instanceof Element ? node : new TextNode(String(node));
      child.parentNode = this;
      this.children.push(child);
      // 浏览器里 select.value 默认取第一个 option；这个桩按同样规则同步。
      if (this.tagName === 'SELECT' && child.tagName === 'OPTION') {
        if (!this.value) this.value = child.value;
        if (child.selected) this.value = child.value;
      }
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'value') this.value = String(value);
    if (name === 'checked') this.checked = true;
    if (name === 'disabled') this.disabled = true;
    if (name === 'hidden') this.hidden = true;
    if (name === 'selected') this.selected = true;
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  dispatchEvent(event) {
    event.target ||= this;
    event.currentTarget = this;
    event.preventDefault ||= () => { event.defaultPrevented = true; };
    for (const handler of this.listeners[event.type] || []) handler(event);
    return !event.defaultPrevented;
  }
  click() { return this.dispatchEvent({ type: 'click' }); }
  querySelector(selector) {
    if (selector.startsWith('.')) {
      const name = selector.slice(1);
      return this.descendants().find((node) => node.classList.contains(name)) || null;
    }
    if (selector.startsWith('[')) {
      const match = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
      if (match && this.attributes[match[1]] !== undefined && (match[2] === undefined || this.attributes[match[1]] === match[2])) return this;
    }
    for (const child of this.children) {
      if (child.nodeType !== 1) continue;
      const found = child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
  descendants() {
    const out = [];
    for (const child of this.children) {
      if (child.nodeType !== 1) continue;
      out.push(child, ...child.descendants());
    }
    return out;
  }
  closest(selector) {
    let node = this;
    while (node && node.nodeType === 1) {
      if (node.matches(selector)) return node;
      node = node.parentNode;
    }
    return null;
  }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('[')) {
      const match = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
      return Boolean(match && this.attributes[match[1]] !== undefined && (match[2] === undefined || this.attributes[match[1]] === match[2]));
    }
    return this.tagName === selector.toUpperCase();
  }
}

export function installDom() {
  globalThis.Node = Element;
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => new TextNode(text),
    body: new Element('body'),
  };
  return { Element, TextNode };
}

export { Element, TextNode };
