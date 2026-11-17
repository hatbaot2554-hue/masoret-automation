const fs = require('node:fs');
const cp = require('node:child_process');
const read = name => JSON.parse(fs.readFileSync(name, 'utf8'));
const old = name => JSON.parse(cp.execFileSync('git', ['show', '7947f6035f85426e5780ec5f1c3f7398baeb9db4:' + name], { encoding: 'utf8', maxBuffer: 100000000 }));
const products = read('products.json');
const seen = new Set(products.map(p => p.url));
let restored = 0;
for (const p of old('products.json')) {
  if (seen.has(p.url)) continue;
  products.push({ ...p, in_stock: false, stock_text: 'ממתין לאימות מחיר ומלאי', needs_revalidation: true });
  seen.add(p.url); restored++;
}
const categories = read('categories.json');
for (const p of products) {
  const parent = p.parent_category || p.category;
  if (!parent) continue;
  let row = categories.find(c => c.parent === parent);
  if (!row) { row = { parent, children: [] }; categories.push(row); }
  if (p.child_category && p.child_category !== parent && !row.children.includes(p.child_category)) row.children.push(p.child_category);
}
const urls = [...new Set([...read('all_urls.json'), ...products.map(p => p.url).filter(Boolean)])];
for (const [name, value] of Object.entries({ 'products.json': products, 'categories.json': categories, 'all_urls.json': urls })) fs.writeFileSync(name, JSON.stringify(value, null, 2) + '\n');
console.log({ restored, total: products.length, categories: categories.length });
