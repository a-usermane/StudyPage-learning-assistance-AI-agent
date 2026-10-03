import {PDFReader} from './pdf.js';
import {TextReader} from './text.js';
export function createReader(doc, container, viewer, onLocation) {
  return new (doc.extension === '.pdf' ? PDFReader : TextReader)(container, viewer, onLocation);
}
