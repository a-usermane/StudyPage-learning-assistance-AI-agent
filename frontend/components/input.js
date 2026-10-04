// Shared autosizing and folded editing; draft storage belongs to the caller.
export class AutoGrowInput {
  constructor(element, {min = 44, max = 180} = {}) {
    this.element = element; this.min = min; this.max = max;
    element.addEventListener('input', () => this.resize());
    this.resize();
  }
  resize() {
    if (!this.element.offsetParent) return;
    this.element.style.height = 'auto';
    const height = Math.max(this.min, Math.min(this.max, this.element.scrollHeight));
    this.element.style.height = height + 'px';
    this.element.style.overflowY = this.element.scrollHeight > this.max ? 'auto' : 'hidden';
  }
  setValue(value) { this.element.value = value; this.resize(); }
}
export class FoldedInput {
  constructor({entry, editor, question, note, collapse, onExpand, onCollapse}) {
    this.entry = entry; this.editor = editor; this.question = question; this.note = note;
    this.growQuestion = new AutoGrowInput(question, {min: 76, max: 150});
    this.growNote = new AutoGrowInput(note, {min: 76, max: 150});
    entry.onclick = onExpand; collapse.onclick = onCollapse;
  }
  render({expanded, isNote, value, placeholder, busy}) {
    this.entry.hidden = expanded; this.editor.hidden = !expanded;
    this.entry.textContent = value.trim() ? value.trim().replace(/\s+/g, ' ').slice(0, 55) : placeholder;
    this.entry.title = value.trim() ? '展开并继续编辑' : placeholder;
    this.entry.setAttribute('aria-expanded', String(expanded));
    this.question.hidden = isNote; this.note.hidden = !isNote;
    const input = isNote ? this.note : this.question;
    input.placeholder = placeholder; input.disabled = busy;
    (isNote ? this.growNote : this.growQuestion).setValue(value);
  }
  focus(isNote) { (isNote ? this.note : this.question).focus(); }
}
