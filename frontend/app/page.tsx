'use client';

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import JSZip from 'jszip';

type AttrName = 'Strength'|'Dexterity'|'Agility'|'Constitution'|'Perception'|'Will'|'Intelligence';
type SaveInfo = { name: string; path: string; modified?: string; modified_ts?: number };
type InventoryWeightItem = { slot: number; name: string; path: string; category: string; stack: number; wiki_type?: string | null; single_weight?: number | null; total_weight?: number | null; percent_of_known_weight?: number | null; quality?: number | null; datafile_key: string; wiki_page?: string | null; wiki_url?: string | null; icon_path?: string | null; icon_image?: string | null; icon_source_url?: string | null };
type InventoryWeightCategory = { category: string; weight: number; percent_of_known_weight?: number | null; known_items: number; unknown_items: number; stacks: number };
type InventoryWeightBreakdown = { target: string; item_count: number; known_weight_total: number; unknown_weight_items: number; items: InventoryWeightItem[]; per_item_heaviest?: InventoryWeightItem[]; unknown_items: InventoryWeightItem[]; categories: InventoryWeightCategory[]; notes: string[] };
type StaticUploadCatalogItem = { datafile?: string; datafile_key: string; name: string; page?: string; type?: string; weight: number; value?: number };
type StaticUploadResult = { source: string; item_count: number; known_weight_total: number; items: InventoryWeightItem[]; categories: InventoryWeightCategory[]; notes: string[] };
type EquippedItem = InventoryWeightItem & { label: string; slot: string; equipped: boolean; durability?: number | null; battery?: number | null; description?: string | null; definition_weight?: number | null; combat?: any };
type EquippedItems = { slots: EquippedItem[]; notes: string[] };
type DamagePart = { type?: string; min?: number; max?: number };
type DamageEstimates = { weapon_skill_scalars: Record<string, { effective_skill: number; normal_weapon_damage_multiplier: number; formula: string; source: string }>; psi_abilities: Array<{ name: string; school: string; effective_skill: number; damage: DamagePart[]; target_health_percent?: number; formula: string; source: string }>; equipped_weapon_estimates: Array<{ slot: string; name: string; skill?: string | null; effective_skill?: number; multiplier?: number; base_damage: DamagePart[]; estimated_damage: DamagePart[]; formula?: string; source?: string; note?: string }>; notes: string[] };
type AnalyzeState = {
  path: string;
  save_folder: string;
  inferred_level?: number;
  attributes: Record<string, { base: number; modified: number; bonus: number }>;
  skills: Record<string, { allocated: number; effective: number; bonus: number }>;
  totals: { attribute_base: number; skill_allocated: number };
  budgets: { attribute_budget: number; attribute_remaining: number; skill_budget: number; skill_remaining: number };
  detected_feats: string[];
  feat_records: Array<{ offset: number; length: number; feat_id: string; display_name: string }>;
  all_known_feats: string[];
  all_feat_ids: Record<string, string>;
  tooltips: { attributes: Record<string,string>; skills: Record<string,string>; feats: Record<string,string> };
  community_mods?: CommunityModsCatalog;
  faction_relations?: Array<{ id: string; name: string; offset: number; player_relation?: { target: string; value: number; label: string; value_offset: number }; confidence: string }>;
  faction_relation_comparison?: { baseline_name: string; baseline_path: string; note: string; deltas: Array<{ id: string; name: string; baseline_value: number; baseline_label: string; current_value: number; current_label: string; current_value_offset?: number }> };
  area_markers?: { markers: any[]; kill_markers: any[]; areas: Array<{ area_id: string; area_label: string; markers: any[]; kill_markers: any[] }>; prefix_legend: Record<string,string>; area_legend: Record<string,string>; notes: string[] };
  inventory_weight?: InventoryWeightBreakdown;
  equipped_items?: EquippedItems;
  damage_estimates?: DamageEstimates;
};

type CommunityMod = { id: string; name: string; category: string; effect: string; integration_signal: string; default_from_source?: string; save_editor_action: string };
type CommunityModsCatalog = { source: { name?: string; url?: string; reviewed_commit?: string; license_note?: string }; scope_note?: string; mods: CommunityMod[]; design_implications: string[] };
type HoverInfo = { title: string; text: string; kind?: string } | null;

const API = process.env.NEXT_PUBLIC_UNDERAIL_API || '';
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || (typeof window !== 'undefined' && window.location.pathname.startsWith('/underrail-respec-editor') ? '/underrail-respec-editor' : '');
function publicAsset(path: string) {
  if (!path || /^https?:\/\//i.test(path) || path.startsWith('data:')) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${BASE_PATH}${normalized}`;
}
const MAX_STATIC_UPLOAD_BYTES = 75 * 1024 * 1024;
const MAX_STATIC_ZIP_ENTRIES = 2500;

const ATTRS: AttrName[] = ['Strength','Dexterity','Agility','Constitution','Perception','Will','Intelligence'];
const SKILLS = ['Guns','Heavy Guns','Throwing','Crossbows','Melee','Dodge','Evasion','Stealth','Hacking','Lockpicking','Pickpocketing','Traps','Mechanics','Electronics','Chemistry','Biology','Tailoring','Thought Control','Psychokinesis','Metathermics','Temporal Manipulation','Persuasion','Intimidation','Mercantile'];
const SKILL_GROUPS = [
  ['Guns','Heavy Guns','Throwing','Crossbows','Melee'],
  ['Dodge','Evasion','Stealth','Hacking','Lockpicking','Pickpocketing','Traps'],
  ['Mechanics','Electronics','Chemistry','Biology','Tailoring'],
  ['Thought Control','Psychokinesis','Metathermics','Temporal Manipulation'],
  ['Persuasion','Intimidation','Mercantile'],
];

const ITEM_ICON_OVERRIDES: Record<string, string> = {
  'expendables\\explosives\\tnt': '/wiki-icons/tnt-charge.png',
  'armor\\rathoundregalia': '/wiki-icons/rathound-regalia.png',
  'devices\\electronicrepairkit2': '/wiki-icons/advanced-electronic-repair-kit.png',
  'devices\\repairkit2': '/wiki-icons/advanced-patching-kit.png',
  'devices\\repairkit': '/wiki-icons/patching-kit.png',
  'ammo\\bolt': '/wiki-icons/bolt.png',
  'currency\\stygiancoin': '/wiki-icons/stygian-coin.png',
};

const CATEGORY_VISUALS: Record<string, { icon: string; tone: string }> = {
  ammo: { icon: '➶', tone: 'blue' },
  armor: { icon: '◈', tone: 'amber' },
  devices: { icon: '✚', tone: 'green' },
  expendables: { icon: '✦', tone: 'red' },
  components: { icon: '⚙', tone: 'violet' },
  currency: { icon: '¤', tone: 'gold' },
  weapons: { icon: '⚔', tone: 'red' },
};

function wikiUrl(title?: string | null) {
  const clean = (title || '').trim();
  if (!clean) return '';
  return `https://www.stygiansoftware.com/wiki/index.php?title=${encodeURIComponent(clean).replace(/%20/g, '+')}`;
}

function WikiLink({ title, wikiTitle, children, className = 'wikiGenericLink' }: { title?: string | null; wikiTitle?: string | null; children?: ReactNode; className?: string }) {
  const pageTitle = wikiTitle || title;
  const href = wikiUrl(pageTitle);
  if (!href) return <>{children || pageTitle}</>;
  return <a className={className} href={href} target="_blank" rel="noreferrer" title={`Open ${pageTitle} on the Underrail Wiki`} onClick={e => e.stopPropagation()}>{children || pageTitle}<span aria-hidden="true">↗</span></a>;
}

function categoryVisual(category?: string) {
  return CATEGORY_VISUALS[(category || '').toLowerCase()] || { icon: '◆', tone: 'neutral' };
}

function itemIcon(item: InventoryWeightItem) {
  return publicAsset(item.icon_path || ITEM_ICON_OVERRIDES[item.datafile_key?.toLowerCase()] || '');
}

function ItemVisual({ item }: { item: InventoryWeightItem }) {
  const icon = itemIcon(item);
  const visual = categoryVisual(item.category);
  return <span className={`itemVisual tone-${visual.tone}`}>{icon ? <img src={icon} alt="" /> : <span>{visual.icon}</span>}</span>;
}

function ItemName({ item }: { item: InventoryWeightItem }) {
  const label = item.name || item.path;
  const href = item.wiki_url || wikiUrl(item.wiki_page || label);
  return <a className="wikiItemLink" href={href} target="_blank" rel="noreferrer" title={`Open ${label} on the Underrail Wiki`} onClick={e => e.stopPropagation()}>{label}<span aria-hidden="true">↗</span></a>;
}

async function api(path: string, body?: unknown) {
  const response = await fetch(API + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  });
  const json = await response.json();
  if (!response.ok || json.error) throw new Error(json.error || response.statusText);
  return json;
}

function InfoPanel({ hoverInfo }: { hoverInfo: HoverInfo }) {
  return (
    <aside className="infoPanel">
      <div className="infoKicker">Mouse-over wiki help</div>
      {hoverInfo ? <>
        <h3>{hoverInfo.title}</h3>
        <div className="tag">{hoverInfo.kind}</div>
        <p>{hoverInfo.text || 'No wiki tooltip text was found for this item yet.'}</p>
      </> : <>
        <h3>Hover a base attribute, skill, or feat</h3>
        <p>The original HTML used native browser title tooltips, which are easy to miss. This Next.js UI shows the wiki text here persistently while you inspect and modify the build.</p>
      </>}
    </aside>
  );
}

function StatRow({ name, current, bonus, value, onChange, tip, kind, setHoverInfo }: any) {
  const effective = value + bonus;
  return (
    <div
      role="group"
      className={'statCard ' + (value !== current ? 'changed' : '')}
      onMouseEnter={() => setHoverInfo({ title: name, text: tip, kind })}
      onFocus={() => setHoverInfo({ title: name, text: tip, kind })}
    >
      <span className="statName"><WikiLink title={name}>{name}</WikiLink></span>
      <span className="stepper" onClick={(e) => { e.stopPropagation(); onChange(Math.max(kind === 'Base attribute' ? 1 : 0, value - 1)); }}>−</span>
      <input value={value} onChange={e => onChange(Number(e.target.value || 0))} onClick={e => e.stopPropagation()} />
      <span className="stepper" onClick={(e) => { e.stopPropagation(); onChange(value + 1); }}>+</span>
      <span className="effective">{bonus ? `eff ${effective}` : ''}</span>
    </div>
  );
}

function fmtWeight(value?: number | null) {
  return value == null ? '?' : value.toFixed(value >= 100 ? 1 : 2);
}

function fmtPct(value?: number | null) {
  return value == null ? '—' : `${value.toFixed(1)}%`;
}

function fmtDamage(parts?: DamagePart[]) {
  if (!parts?.length) return '—';
  return parts.map(p => `${p.min?.toFixed(1) ?? '?'}-${p.max?.toFixed(1) ?? '?'}${p.type ? ` ${p.type}` : ''}`).join(' + ');
}

function EquippedItemsPanel({ equipped }: { equipped?: EquippedItems }) {
  if (!equipped) return null;
  const filled = equipped.slots.filter(s => s.equipped);
  return <section className="gamePanel equippedPanel">
    <div className="panelTitle">Current equipped gear - read only</div>
    <p className="referenceNote">Decoded from the character gear sheet in <code>global.dat</code>. Crafted gear uses save-derived names when the wiki datafile path is not directly available.</p>
    <div className="equipmentGrid">{equipped.slots.map(item => <article key={item.slot} className={item.equipped ? 'equipmentCard filled' : 'equipmentCard empty'}>
      <div className="equipSlot">{item.label}</div>
      {item.equipped ? <>
        <div className="equipIdentity"><ItemVisual item={item} /><div><ItemName item={item} /><small>{item.wiki_type || item.datafile_key || item.path}</small></div></div>
        <div className="miniStats"><span>Wt {fmtWeight(item.single_weight ?? item.definition_weight)}</span>{item.durability != null && <span>Dur {Math.round(item.durability)}</span>}{item.battery != null && item.battery > 0 && <span>Energy {Math.round(item.battery)}</span>}</div>
      </> : <div className="muted">Empty</div>}
    </article>)}</div>
    <div className="runtimeReport">Equipped slots filled: {filled.length}/{equipped.slots.length}</div>
  </section>;
}

function DamageEstimatesPanel({ estimates }: { estimates?: DamageEstimates }) {
  if (!estimates) return null;
  return <section className="gamePanel damagePanel">
    <div className="panelTitle">Skill damage estimates / PSI ability preview</div>
    <p className="referenceNote">Best-effort read-only formulas from normalized Underrail Wiki notes. These use effective save skills and exclude target armor/resists, crits, ammo effects, temporary buffs, and many conditional feat/equipment modifiers unless stated.</p>
    <div className="damageColumns">
      <div>
        <h3>Equipped weapon normal attacks</h3>
        <div className="damageList">{estimates.equipped_weapon_estimates.map(row => <article key={`${row.slot}-${row.name}`} className="damageCard">
          <div><b><WikiLink wikiTitle={row.name} title={row.name}>{row.name}</WikiLink></b><span>{row.skill ? <WikiLink title={row.skill}>{row.skill}</WikiLink> : 'unknown skill'}{row.effective_skill != null ? ` eff ${row.effective_skill}` : ''}</span></div>
          <p>{fmtDamage(row.base_damage)} → <b>{fmtDamage(row.estimated_damage)}</b></p>
          <small>{row.formula || row.note}</small>
        </article>)}</div>
      </div>
      <div>
        <h3>PSI abilities</h3>
        <div className="damageList">{estimates.psi_abilities.map(row => <article key={row.name} className="damageCard psi">
          <div><b><WikiLink wikiTitle={row.name} title={row.name}>{row.name}</WikiLink></b><span><WikiLink title={row.school}>{row.school}</WikiLink> eff {row.effective_skill}</span></div>
          <p>{row.target_health_percent != null ? `${row.target_health_percent}% target HP explosion` : fmtDamage(row.damage)}</p>
          <small>{row.formula}</small>
        </article>)}</div>
      </div>
    </div>
  </section>;
}

function catalogCategory(key: string) {
  return (key || '').split('\\')[0] || 'unknown';
}

async function maybeUnpackGlobalDat(blob: Blob) {
  const raw = await blob.arrayBuffer();
  const bytes = new Uint8Array(raw);
  const start = bytes.length > 26 && bytes[24] === 0x1f && bytes[25] === 0x8b ? 24 : 0;
  const payload = bytes.slice(start);
  if (payload[0] !== 0x1f || payload[1] !== 0x8b) return raw;
  const Decompression = (globalThis as any).DecompressionStream;
  if (!Decompression) throw new Error('This browser does not expose DecompressionStream for local gzip global.dat analysis. Use the local Python API mode instead.');
  const stream = new Blob([payload]).stream().pipeThrough(new Decompression('gzip'));
  return await new Response(stream).arrayBuffer();
}

function textFromPayload(payload: ArrayBuffer) {
  const bytes = new Uint8Array(payload);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return binary.toLowerCase();
}

function countOccurrences(haystack: string, needle: string) {
  let count = 0;
  let at = haystack.indexOf(needle);
  while (at !== -1) {
    count += 1;
    at = haystack.indexOf(needle, at + Math.max(1, needle.length));
  }
  return count;
}

function staticAnalyzePayload(source: string, payload: ArrayBuffer, catalog: StaticUploadCatalogItem[]): StaticUploadResult {
  const text = textFromPayload(payload);
  const rows: InventoryWeightItem[] = [];
  for (const entry of catalog) {
    const key = entry.datafile_key.toLowerCase();
    const datafile = (entry.datafile || `${key}.item`).replace(/\\/g, '\\').toLowerCase();
    const variants = Array.from(new Set([key, datafile.replace(/\.item$/i, ''), datafile]));
    const seen = Math.max(...variants.map(variant => countOccurrences(text, variant)));
    if (!seen) continue;
    rows.push({
      slot: rows.length,
      name: entry.name,
      path: entry.datafile || entry.datafile_key,
      category: catalogCategory(entry.datafile_key),
      stack: seen,
      single_weight: Number(entry.weight),
      total_weight: Number(entry.weight) * seen,
      datafile_key: entry.datafile_key,
      wiki_page: entry.page,
      wiki_url: entry.page ? wikiUrl(entry.page) : undefined,
    });
  }
  const known = rows.reduce((sum, row) => sum + (row.total_weight || 0), 0);
  rows.forEach(row => row.percent_of_known_weight = known ? (row.total_weight || 0) / known * 100 : null);
  rows.sort((a, b) => (b.total_weight || 0) - (a.total_weight || 0));
  const categoryMap = new Map<string, InventoryWeightCategory>();
  for (const row of rows) {
    const bucket = categoryMap.get(row.category) || { category: row.category, weight: 0, known_items: 0, unknown_items: 0, stacks: 0 };
    bucket.weight += row.total_weight || 0;
    bucket.known_items += 1;
    bucket.stacks += row.stack;
    categoryMap.set(row.category, bucket);
  }
  const categories = Array.from(categoryMap.values()).map(row => ({ ...row, percent_of_known_weight: known ? row.weight / known * 100 : null })).sort((a, b) => b.weight - a.weight);
  return {
    source,
    item_count: rows.length,
    known_weight_total: known,
    items: rows,
    categories,
    notes: [
      'Browser-only GitHub Pages mode: the file never leaves your machine.',
      'Static analysis is heuristic: it scans decompressed save bytes for known item datafile paths and cannot fully decode .NET BinaryFormatter object graphs or exact stack fields like the local Python API.',
    ],
  };
}

async function filesFromUpload(fileList: FileList | null) {
  const files = Array.from(fileList || []);
  const out: Array<{ name: string; blob: Blob }> = [];
  for (const file of files) {
    if (file.size > MAX_STATIC_UPLOAD_BYTES) throw new Error(`${file.name} is too large for browser-only analysis. Limit: 75 MB.`);
    if (file.name.toLowerCase().endsWith('.zip')) {
      const zip = await JSZip.loadAsync(file);
      const entries = Object.entries(zip.files);
      if (entries.length > MAX_STATIC_ZIP_ENTRIES) throw new Error(`Zip has too many entries for browser-only analysis. Limit: ${MAX_STATIC_ZIP_ENTRIES}.`);
      for (const [name, entry] of entries) {
        if (!entry.dir && name.toLowerCase().endsWith('global.dat')) {
          out.push({ name, blob: await entry.async('blob') });
        }
      }
    } else if (file.name.toLowerCase() === 'global.dat' || file.name.toLowerCase().endsWith('.dat')) {
      out.push({ name: (file as any).webkitRelativePath || file.name, blob: file });
    }
  }
  return out;
}

function StaticUploadAnalyzer({ setHoverInfo }: { setHoverInfo: (info: HoverInfo) => void }) {
  const [result, setResult] = useState<StaticUploadResult | null>(null);
  const [uploadMessage, setUploadMessage] = useState('Choose global.dat, a save folder, or a zip containing global.dat.');
  async function analyzeFiles(fileList: FileList | null) {
    try {
      setUploadMessage('Reading browser-local files…');
      const catalogResponse = await fetch(publicAsset('/data/item_weights.json'), { cache: 'force-cache' });
      if (!catalogResponse.ok) throw new Error('Could not load bundled item weight catalog.');
      const catalogJson = await catalogResponse.json();
      const catalog: StaticUploadCatalogItem[] = catalogJson.items || [];
      const candidates = await filesFromUpload(fileList);
      if (!candidates.length) throw new Error('No global.dat file was found in that upload.');
      const chosen = candidates[0];
      const payload = await maybeUnpackGlobalDat(chosen.blob);
      const analyzed = staticAnalyzePayload(chosen.name, payload, catalog);
      setResult(analyzed);
      setUploadMessage(`Analyzed ${chosen.name}: ${analyzed.item_count} likely catalog item path(s) found.`);
      setHoverInfo({ title: 'Static upload analyzer', kind: 'GitHub Pages mode', text: analyzed.notes.join(' ') });
    } catch (error: any) {
      setUploadMessage(error?.message || String(error));
      setResult(null);
    }
  }
  return <section className="gamePanel staticUploadPanel">
    <div className="panelTitle">Static GitHub Pages analyzer - no local API required</div>
    <p className="referenceNote">For hosted/static mode only. Uploads stay in your browser; this cannot patch saves or run the full Python BinaryFormatter parser, but it can provide a quick inventory-weight heuristic from a <code>global.dat</code>, save folder, or zip.</p>
    <div className="uploadGrid">
      <label className="uploadDrop">global.dat / zip<input type="file" accept=".dat,.zip" onChange={e => analyzeFiles(e.target.files)} /></label>
      <label className="uploadDrop">save folder<input type="file" multiple {...{ webkitdirectory: 'true', directory: 'true' }} onChange={e => analyzeFiles(e.target.files)} /></label>
    </div>
    <div className="message">{uploadMessage}</div>
    {result && <>
      <div className="weightSummaryGrid">
        <div><b>{fmtWeight(result.known_weight_total)}</b><span>heuristic known weight</span><small>{result.source}</small></div>
        <div><b>{result.item_count}</b><span>likely item paths</span><small>catalog matches</small></div>
        <div><b>{result.categories.length}</b><span>categories</span><small>browser-local</small></div>
      </div>
      <div className="categoryBars">{result.categories.slice(0, 8).map(category => <CategoryBar key={category.category} category={category} setHoverInfo={setHoverInfo} />)}</div>
      <div className="inventoryCubeGrid compact">{result.items.slice(0, 48).map(item => <ItemCube key={`static-${item.datafile_key}`} item={item} setHoverInfo={setHoverInfo} />)}</div>
    </>}
  </section>;
}

function itemHoverText(item: InventoryWeightItem, mode: 'stack' | 'single' = 'stack') {
  const slot = String(item.slot).padStart(3, '0');
  const common = `Slot #${slot}: x${item.stack}; each ${fmtWeight(item.single_weight)}; stack ${fmtWeight(item.total_weight)}; category ${item.category}. Path: ${item.path}${item.quality ? `, quality ${item.quality}` : ''}.`;
  return mode === 'single' ? `Reducing this stack by exactly one item lowers carry weight by ${fmtWeight(item.single_weight)}. ${common}` : common;
}

function CategoryFilterBar({ categories, selectedInventoryCategory, setSelectedInventoryCategory }: { categories: InventoryWeightCategory[]; selectedInventoryCategory: string; setSelectedInventoryCategory: (category: string) => void }) {
  return <div className="categoryFilterBar" aria-label="Inventory category filter">
    <button type="button" className={selectedInventoryCategory === 'all' ? 'categoryFilterChip active' : 'categoryFilterChip'} onClick={() => setSelectedInventoryCategory('all')}>All</button>
    {categories.map(category => {
      const visual = categoryVisual(category.category);
      return <button key={category.category} type="button" className={selectedInventoryCategory === category.category ? `categoryFilterChip active tone-${visual.tone}` : `categoryFilterChip tone-${visual.tone}`} onClick={() => setSelectedInventoryCategory(category.category)}>
        <span>{visual.icon}</span>{category.category}<small>{fmtWeight(category.weight)}</small>
      </button>;
    })}
  </div>;
}

function ItemCube({ item, setHoverInfo, mode = 'stack' }: { item: InventoryWeightItem; setHoverInfo: (info: HoverInfo) => void; mode?: 'stack' | 'single' }) {
  const visual = categoryVisual(item.category);
  const icon = itemIcon(item);
  const primary = mode === 'single' ? item.single_weight : item.total_weight;
  return <article className={`inventoryCube tone-${visual.tone}`} onMouseEnter={() => setHoverInfo({ title: item.name || item.path, kind: mode === 'single' ? 'Per-item weight impact' : 'Inventory item weight', text: itemHoverText(item, mode) })}>
    <div className="cubeIcon">{icon ? <img src={icon} alt="" /> : <span>{visual.icon}</span>}</div>
    <div className="cubeOverlay topLeft">#{String(item.slot).padStart(3, '0')}</div>
    {item.stack > 1 && <div className="cubeOverlay topRight">x{item.stack}</div>}
    <div className="cubeOverlay bottomLeft">{mode === 'single' ? 'one' : 'stack'} {fmtWeight(primary)}</div>
    <div className="cubeOverlay bottomRight">{fmtWeight(item.single_weight)} ea</div>
    <div className="cubeName"><ItemName item={item} /></div>
  </article>;
}

type InventoryWeightTab = 'summary' | 'categories' | 'heaviest' | 'perItem' | 'unknown';
type MainTab = 'character' | 'inventory' | 'factions' | 'qol';

function InventoryWeightPanel({ breakdown, setHoverInfo }: { breakdown?: InventoryWeightBreakdown; setHoverInfo: (info: HoverInfo) => void }) {
  const [inventoryWeightTab, setInventoryWeightTab] = useState<InventoryWeightTab>('summary');
  const [selectedInventoryCategory, setSelectedInventoryCategory] = useState('all');
  if (!breakdown) return null;
  const visibleItems = selectedInventoryCategory === 'all' ? breakdown.items : breakdown.items.filter(item => item.category === selectedInventoryCategory);
  const visiblePerItemHeavy = selectedInventoryCategory === 'all' ? (breakdown.per_item_heaviest || []) : (breakdown.per_item_heaviest || []).filter(item => item.category === selectedInventoryCategory);
  const heavyItems = visibleItems.slice(0, 60);
  const perItemHeavyItems = visiblePerItemHeavy.slice(0, 60);
  const filteredCategoryItems = visibleItems.filter(item => item.total_weight != null);
  const unknowns = selectedInventoryCategory === 'all' ? (breakdown.unknown_items || []) : (breakdown.unknown_items || []).filter(item => item.category === selectedInventoryCategory);
  const topCategories = breakdown.categories.slice(0, 6);
  const tabs: Array<[InventoryWeightTab, string, string, string]> = [
    ['summary', '▦', 'Summary', 'Totals + quick answers'],
    ['categories', '◫', 'Categories', 'Where weight clusters'],
    ['heaviest', '▰', 'Heaviest stacks', 'Best stacks to dump'],
    ['perItem', '◆', 'Heaviest per item', 'One-count weight drop'],
    ['unknown', '?', 'Unknown weights', 'Catalog gaps'],
  ];
  return (
    <section className="gamePanel inventoryWeightPanel">
      <div className="panelTitle">Inventory weight breakdown - read only</div>
      <p className="referenceNote">Save inventory diagnosis only. This panel reads <code>global.dat</code>, joins known item paths to wiki-derived weights, and never writes item/save changes. Percentages are over known weights only.</p>
      <div className="weightSummaryGrid">
        <div><b>{fmtWeight(breakdown.known_weight_total)}</b><span>known weight</span><small>joined wiki catalog</small></div>
        <div><b>{breakdown.item_count}</b><span>inventory rows</span><small>parsed from global.dat</small></div>
        <div><b>{breakdown.unknown_weight_items}</b><span>unknown rows</span><small>excluded from math</small></div>
        <div><b>{fmtWeight(perItemHeavyItems[0]?.single_weight)}</b><span>largest one-count drop</span><small>{perItemHeavyItems[0]?.name || 'load known weights'}</small></div>
      </div>
      <div className="weightTabBar" role="tablist" aria-label="Inventory weight breakdown tabs">
        {tabs.map(([id, icon, label, detail]) => <button key={id} type="button" role="tab" aria-selected={inventoryWeightTab === id} className={inventoryWeightTab === id ? 'weightTab active' : 'weightTab'} onClick={() => setInventoryWeightTab(id)}>
          <span className="tabIcon">{icon}</span><span><b>{label}</b><small>{detail}</small></span>
        </button>)}
      </div>
      <CategoryFilterBar categories={breakdown.categories} selectedInventoryCategory={selectedInventoryCategory} setSelectedInventoryCategory={setSelectedInventoryCategory} />

      {inventoryWeightTab === 'summary' && <div className="weightColumns">
        <div>
          <h3>Top categories</h3>
          <div className="categoryBars">{topCategories.map(c => <CategoryBar key={c.category} category={c} setHoverInfo={setHoverInfo} />)}</div>
        </div>
        <div>
          <h3>Top 10 heaviest stacks</h3>
          <div className="inventoryCubeGrid compact">{heavyItems.slice(0, 12).map(item => <ItemCube key={`${item.slot}-${item.path}`} item={item} setHoverInfo={setHoverInfo} />)}</div>
          <h3>Top single-count reductions</h3>
          <p className="referenceNote">These rows answer: if I remove or reduce exactly one item from this stack, how much carry weight drops.</p>
          <div className="inventoryCubeGrid compact">{perItemHeavyItems.slice(0, 12).map(item => <ItemCube key={`per-${item.slot}-${item.path}`} item={item} setHoverInfo={setHoverInfo} mode="single" />)}</div>
        </div>
      </div>}

      {inventoryWeightTab === 'categories' && <div>
        <h3>Category distribution</h3>
        <div className="categoryBars fullList">{breakdown.categories.map(c => <CategoryBar key={c.category} category={c} setHoverInfo={setHoverInfo} />)}</div>
        <h3>{selectedInventoryCategory === 'all' ? 'All known inventory items' : `${selectedInventoryCategory} only`}</h3>
        <p className="referenceNote">Use the filter chips above to drill into one category, for example components only. Tiles show stack weight, count, slot, and per-item weight; mouse-over shows path and exact details.</p>
        <div className="inventoryCubeGrid">{filteredCategoryItems.map(item => <ItemCube key={`cat-${item.slot}-${item.path}`} item={item} setHoverInfo={setHoverInfo} />)}</div>
      </div>}

      {inventoryWeightTab === 'heaviest' && <div>
        <h3>Heaviest item stacks</h3>
        <div className="inventoryCubeGrid">{heavyItems.map(item => <ItemCube key={`${item.slot}-${item.path}`} item={item} setHoverInfo={setHoverInfo} />)}</div>
      </div>}

      {inventoryWeightTab === 'perItem' && <div>
        <h3>Heaviest per single item</h3>
        <p className="referenceNote">Sorted by single-item weight, not stack total. Reducing one count from a row here reduces carry weight by the displayed one-count value.</p>
        <div className="inventoryCubeGrid">{perItemHeavyItems.map(item => <ItemCube key={`per-${item.slot}-${item.path}`} item={item} setHoverInfo={setHoverInfo} mode="single" />)}</div>
      </div>}

      {inventoryWeightTab === 'unknown' && <div>
        <h3>Unknown weights</h3>
        <p className="referenceNote">These rows were found in the save but are missing from the item weight catalog, so they are excluded from percentage math instead of guessed.</p>
        {unknowns.length > 0 ? <div className="unknownGrid">{unknowns.map(item => <article key={`${item.slot}-${item.path}`} className="unknownWeightBox" onMouseEnter={() => setHoverInfo({ title: item.path, kind: 'Unknown inventory weight', text: `Slot #${String(item.slot).padStart(3, '0')}: x${item.stack}. Add a catalog weight for ${item.path} to include it in totals.` })}>
          <b>#{String(item.slot).padStart(3, '0')} x{item.stack}</b> {item.path}<small>{item.category}</small>
        </article>)}</div> : <div className="validBox">All parsed inventory rows have known catalog weights.</div>}
      </div>}
    </section>
  );
}

function CategoryBar({ category, setHoverInfo }: { category: InventoryWeightCategory; setHoverInfo: (info: HoverInfo) => void }) {
  const visual = categoryVisual(category.category);
  return <div className={`categoryBar tone-${visual.tone}`} onMouseEnter={() => setHoverInfo({ title: category.category, kind: 'Inventory category', text: `${fmtWeight(category.weight)} known weight, ${fmtPct(category.percent_of_known_weight)} of known inventory weight, ${category.unknown_items} unknown row(s).` })}>
    <div className="barHeader"><b><span className="categoryIcon">{visual.icon}</span>{category.category}</b><span>{fmtWeight(category.weight)} · {fmtPct(category.percent_of_known_weight)}</span></div>
    <div className="barTrack"><span style={{ width: `${Math.max(1, Math.min(100, category.percent_of_known_weight || 0))}%` }} /></div>
    <small>known rows {category.known_items} · unknown {category.unknown_items} · stacks {category.stacks}</small>
  </div>;
}

function HeavyItemRow({ item, setHoverInfo }: { item: InventoryWeightItem; setHoverInfo: (info: HoverInfo) => void }) {
  return <article className="heavyRow" onMouseEnter={() => setHoverInfo({ title: item.name || item.path, kind: 'Inventory item weight', text: `Slot #${String(item.slot).padStart(3, '0')}: x${item.stack} at ${fmtWeight(item.single_weight)} each = ${fmtWeight(item.total_weight)} (${fmtPct(item.percent_of_known_weight)} of known weight). Path: ${item.path}${item.quality ? `, quality ${item.quality}` : ''}.` })}>
    <ItemVisual item={item} />
    <div className="heavyWeight"><b>{fmtWeight(item.total_weight)}</b><span>{fmtPct(item.percent_of_known_weight)}</span></div>
    <div className="heavyMain"><ItemName item={item} /><span>x{item.stack} · each {fmtWeight(item.single_weight)} · {item.category}</span><small>#{String(item.slot).padStart(3, '0')} {item.path}{item.quality ? ` · q${item.quality}` : ''}</small></div>
  </article>;
}

function PerItemHeavyRow({ item, setHoverInfo }: { item: InventoryWeightItem; setHoverInfo: (info: HoverInfo) => void }) {
  return <article className="heavyRow perItemHeavyRow" onMouseEnter={() => setHoverInfo({ title: item.name || item.path, kind: 'Per-item weight impact', text: `Reducing this stack by exactly one item lowers carry weight by ${fmtWeight(item.single_weight)}. Slot #${String(item.slot).padStart(3, '0')}: x${item.stack}; full stack ${fmtWeight(item.total_weight)}. Path: ${item.path}${item.quality ? `, quality ${item.quality}` : ''}.` })}>
    <ItemVisual item={item} />
    <div className="heavyWeight"><b>{fmtWeight(item.single_weight)}</b><span>per item</span></div>
    <div className="heavyMain"><ItemName item={item} /><span>one-count drop {fmtWeight(item.single_weight)} · stack {fmtWeight(item.total_weight)} · x{item.stack}</span><small>#{String(item.slot).padStart(3, '0')} {item.category} · {item.path}{item.quality ? ` · q${item.quality}` : ''}</small></div>
  </article>;
}

export default function Page() {
  const [savePath, setSavePath] = useState('');
  const [sort, setSort] = useState('modified');
  const [saves, setSaves] = useState<SaveInfo[]>([]);
  const [state, setState] = useState<AnalyzeState | null>(null);
  const [attrs, setAttrs] = useState<Record<string, number>>({});
  const [skills, setSkills] = useState<Record<string, number>>({});
  const [selectedFeats, setSelectedFeats] = useState<Set<string>>(new Set());
  const [hoverInfo, setHoverInfo] = useState<HoverInfo>(null);
  const [level, setLevel] = useState(12);
  const [attrBudget, setAttrBudget] = useState(0);
  const [skillBudget, setSkillBudget] = useState(0);
  const [ignoreBudget, setIgnoreBudget] = useState(false);
  const [newName, setNewName] = useState('');
  const [message, setMessage] = useState('List or load a save. In portable mode, the bundled Python API is already running.');
  const [validation, setValidation] = useState<any>(null);
  const [gameDir, setGameDir] = useState('');
  const [runtimeScan, setRuntimeScan] = useState<any>(null);
  const [throwingCap, setThrowingCap] = useState(0.99);
  const [weightMultiplier, setWeightMultiplier] = useState(0.1);
  const [runtimeModSelection, setRuntimeModSelection] = useState<Record<string, boolean>>({ item_weight: true, force_restock: false, traders_buy_all: false, fastforward: false, throwing_chance_cap: false });
  const [lastRuntimeBackup, setLastRuntimeBackup] = useState('');
  const [runtimeActionResult, setRuntimeActionResult] = useState('');
  const [runtimeStatus, setRuntimeStatus] = useState<any>({ underrail_running: false, locked: false, message: 'Underrail status not checked yet.' });
  const [mainTab, setMainTab] = useState<MainTab>('character');

  const hostedStaticMode = !!BASE_PATH && !API;

  const featList = useMemo(() => state ? Array.from(new Set([...(state.all_known_feats || []), ...(state.detected_feats || [])])).sort() : [], [state]);
  const runtimeLocked = !!runtimeStatus?.locked;
  const factionRows = state?.faction_relations || [];
  const factionComparison = state?.faction_relation_comparison;
  const changedToHostile = factionComparison?.deltas?.filter((d: any) => d.current_value === 0 && d.baseline_value !== 0) || [];
  const hostileFactionRows = factionRows.filter((f: any) => f.player_relation?.value === 0);
  const areaMarkers = state?.area_markers;
  const areaRows = areaMarkers?.areas || [];
  const killMarkers = areaMarkers?.kill_markers || [];
  const mainTabs: Array<[MainTab, string, string, string]> = [
    ['character', '◉', 'Character editing', 'Skills, traits/feats, specialization-point planning, budgets, and clone-first save writing.'],
    ['inventory', '▣', 'Inventory', 'Read-only carry-weight breakdown: categories, heaviest stacks, and unknown catalog weights.'],
    ['factions', '◇', 'Faction hostilities', 'Read-only faction relation and area/kill marker diagnostics.'],
    ['qol', '⚙', 'QoL patching', 'Runtime quality-of-life patching, dry-run/backup/rollback, and external modding references.'],
  ];

  async function refreshRuntimeStatus(showMessage = false) {
    const result = await api('/api/runtime/status');
    setRuntimeStatus(result);
    if (showMessage || result.locked) setMessage(result.message);
    return result;
  }

  useEffect(() => {
    refreshRuntimeStatus(false).catch(() => undefined);
    const timer = window.setInterval(() => refreshRuntimeStatus(false).catch(() => undefined), 5000);
    return () => window.clearInterval(timer);
  }, []);

  async function listSaves() {
    const result = await api(`/api/list-saves?sort=${encodeURIComponent(sort)}`);
    setSaves(result.saves);
    setMessage(`Listed ${result.saves.length} saves (${sort === 'alpha' ? 'A → Z' : sort === 'modified_asc' ? 'oldest first' : 'newest first'}).`);
  }

  async function loadSave(path = savePath) {
    const result: AnalyzeState = await api('/api/analyze', { path, level });
    setState(result);
    setSavePath(result.path);
    setLevel(result.inferred_level || level);
    setAttrBudget(result.budgets.attribute_budget);
    setSkillBudget(result.budgets.skill_budget);
    setAttrs(Object.fromEntries(ATTRS.map(a => [a, result.attributes[a].base])));
    setSkills(Object.fromEntries(SKILLS.map(s => [s, result.skills[s].allocated])));
    setSelectedFeats(new Set(result.detected_feats || []));
    if (!newName) setNewName((result.save_folder.split(/[\\/]/).pop() || 'Save') + '-Respec');
    setMessage(`Loaded ${result.path}`);
    setHoverInfo({ title: 'Save loaded', kind: 'Status', text: 'Hover attributes, skills, or feats to read wiki-derived help in this panel.' });
  }

  async function validate() {
    if (!state) return;
    const result = await api('/api/validate', { current: state, attributes: attrs, skills, feats: Array.from(selectedFeats), level, attr_budget: attrBudget, skill_budget: skillBudget, ignore_budget: ignoreBudget });
    setValidation(result);
  }

  function toggleFeat(name: string) {
    const next = new Set(selectedFeats);
    next.has(name) ? next.delete(name) : next.add(name);
    setSelectedFeats(next);
  }

  async function createRespec() {
    if (!state) return;
    const changedAttrs = Object.fromEntries(ATTRS.filter(a => attrs[a] !== state.attributes[a].base).map(a => [a, attrs[a]]));
    const changedSkills = Object.fromEntries(SKILLS.filter(s => skills[s] !== state.skills[s].allocated).map(s => [s, skills[s]]));
    const result = await api('/api/create-respec', {
      source_folder: state.save_folder,
      new_name: newName,
      attributes: changedAttrs,
      skills: changedSkills,
      feats: Array.from(selectedFeats),
      level,
      attr_budget: attrBudget,
      skill_budget: skillBudget,
      ignore_budget: ignoreBudget,
      feat_replacements: []
    });
    setMessage(`Created cloned save: ${result.destination}`);
  }

  async function scanRuntimeMods() {
    const result = await api(`/api/runtime/scan${gameDir ? `?game_dir=${encodeURIComponent(gameDir)}` : ''}`);
    setRuntimeScan(result);
    setRuntimeStatus({ underrail_running: !!result.underrail_running, locked: !!result.locked, message: result.message });
    setGameDir(result.assembly ? result.assembly.replace(/[\\/]underrail\.exe$/i, '') : gameDir);
    setMessage(result.locked ? result.message : `Runtime scan found ${result.mods?.throwing_chance_cap?.candidate_count ?? 0} throwing-cap patch point(s).`);
  }

  function selectedRuntimeMods() {
    return Object.entries(runtimeModSelection).filter(([, enabled]) => enabled).map(([id]) => id);
  }

  function toggleRuntimeMod(id: string) {
    if (runtimeLocked) { setMessage('Runtime mod controls are locked because Underrail is running. Close the game first.'); return; }
    setRuntimeModSelection({ ...runtimeModSelection, [id]: !runtimeModSelection[id] });
  }

  async function patchSelectedRuntimeMods(dryRun: boolean) {
    const status = await refreshRuntimeStatus(false);
    if (status.locked) { setMessage(status.message); return; }
    const mods = selectedRuntimeMods();
    if (!mods.length) { setMessage('Select at least one runtime mod first.'); return; }
    const result = await api('/api/runtime/patch-mods', { game_dir: gameDir || undefined, mods, cap: throwingCap, weight_multiplier: weightMultiplier, dry_run: dryRun });
    if (result.backup) setLastRuntimeBackup(result.backup);
    const summary = dryRun
      ? (result.text || `Dry-run completed for runtime mods: ${mods.join(', ')}`)
      : `Patched runtime mods: ${mods.join(', ')}. Backup: ${result.backup || 'see patcher response'}`;
    setRuntimeActionResult(summary);
    setMessage(summary);
  }

  async function rollbackRuntimePatch() {
    const status = await refreshRuntimeStatus(false);
    if (status.locked) { setMessage(status.message); return; }
    const result = await api('/api/runtime/rollback', { game_dir: gameDir || undefined, backup: lastRuntimeBackup });
    setMessage(`Rolled back runtime patch from ${result.restored_from}`);
  }

  const attrTotal = Object.values(attrs).reduce((a,b) => a + b, 0);
  const skillTotal = Object.values(skills).reduce((a,b) => a + b, 0);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">Local save editor + runtime mod patcher</div>
          <h1>Underrail Respec & Runtime Mod Tool</h1>
        </div>
        <div className="statusPill">{hostedStaticMode ? 'GitHub Pages static mode: upload analysis only' : `Python API: ${API || 'same-origin'}`}</div>
      </header>

      <section className="loadPanel gamePanel">
        {hostedStaticMode && <div className="validBox">Hosted GitHub Pages mode: local save browsing, clone-save writing, and runtime patching are disabled because there is no Python backend. Use the Inventory tab upload analyzer for browser-only global.dat/folder/zip analysis.</div>}
        <div className="pathRow">
          <input className="pathInput" value={savePath} onChange={e => setSavePath(e.target.value)} placeholder="Save folder or global.dat path" />
          <button onClick={() => loadSave()} disabled={hostedStaticMode}>Load</button>
          <button onClick={listSaves} disabled={hostedStaticMode}>List saves</button>
          <select value={sort} onChange={e => setSort(e.target.value)}>
            <option value="modified">Newest first</option>
            <option value="alpha">A → Z</option>
            <option value="modified_asc">Oldest first</option>
          </select>
        </div>
        {saves.length > 0 && <div className="saveGrid">{saves.map(s => <button key={s.path} onClick={() => loadSave(s.path)}><b>{s.name}</b><span>{s.modified}</span></button>)}</div>}
        <div className="message">{message}</div>
      </section>

      <nav className="mainTabBar" role="tablist" aria-label="Underrail tool workspace tabs">
        {mainTabs.map(([id, icon, label, description]) => <button key={id} type="button" role="tab" aria-selected={mainTab === id} className={mainTab === id ? 'mainTabButton mainTab active' : 'mainTabButton mainTab'} onClick={() => setMainTab(id)} onMouseEnter={() => setHoverInfo({ title: label, kind: 'Workspace tab', text: description })}>
          <span className="mainTabGlyph">{icon}</span><b>{label}</b><span>{description}</span>
        </button>)}
      </nav>

      {mainTab === 'character' && <>
        <div className="layout">
          <section className="gamePanel characterPanel">
            <div className="panelTitle">Character editing - skills / traits / specialization planning</div>
            <div className="attrWheel">
              {ATTRS.map(a => state && <StatRow key={a} name={a} kind="Base attribute" current={state.attributes[a].base} bonus={state.attributes[a].bonus} value={attrs[a] ?? 0} onChange={(v:number) => setAttrs({...attrs, [a]: v})} tip={state.tooltips.attributes[a]} setHoverInfo={setHoverInfo} />)}
            </div>
            <div className="budgetLine">Attributes: {attrTotal}/{attrBudget || 0} remaining {(attrBudget || 0) - attrTotal}</div>

            <div className="panelTitle">Skills</div>
            <div className="skillColumns">
              {SKILL_GROUPS.map((group, i) => <div className="skillGroup" key={i}>{group.map(s => state && <StatRow key={s} name={s} kind="Skill" current={state.skills[s].allocated} bonus={state.skills[s].bonus} value={skills[s] ?? 0} onChange={(v:number) => setSkills({...skills, [s]: v})} tip={state.tooltips.skills[s]} setHoverInfo={setHoverInfo} />)}</div>)}
            </div>
            <div className="budgetLine">Skills: {skillTotal}/{skillBudget || 0} remaining {(skillBudget || 0) - skillTotal}</div>
          </section>

          <section className="gamePanel sidePanel">
            <InfoPanel hoverInfo={hoverInfo} />
            <div className="panelTitle">Budgets / clone-first write</div>
            <label>Level <input type="number" value={level} onChange={e => setLevel(Number(e.target.value))} /></label>
            <label>Attr budget <input type="number" value={attrBudget} onChange={e => setAttrBudget(Number(e.target.value))} /></label>
            <label>Skill budget <input type="number" value={skillBudget} onChange={e => setSkillBudget(Number(e.target.value))} /></label>
            <label className="check"><input type="checkbox" checked={ignoreBudget} onChange={e => setIgnoreBudget(e.target.checked)} /> Ignore point budget</label>
            <button className="wide" onClick={validate} disabled={!state || hostedStaticMode}>Validate build</button>
            <label>New save <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="JetSki-Respec" /></label>
            <button className="wide" onClick={createRespec} disabled={!state || !newName || hostedStaticMode}>Create cloned save</button>
            {validation && <div className={validation.valid ? 'validBox' : 'invalidBox'}>{validation.valid ? 'Valid' : 'Blocked'}<br />{validation.issues?.map((x:any) => <div key={x.message}>{x.message}</div>)}</div>}
          </section>
        </div>

        <section className="gamePanel featsPanel">
          <div className="panelTitle">Traits / feats / specialization guardrails</div>
          <p className="referenceNote">Selected feats are validated against wiki-derived prerequisites. Specialization-point editing is not yet mapped; this tab is where those controls should live once save offsets are verified.</p>
          <div className="featGrid">{featList.map(f => <label key={f} onMouseEnter={() => setHoverInfo({ title: f, kind: 'Feat', text: state?.tooltips.feats[f] || '' })}>
            <input type="checkbox" checked={selectedFeats.has(f)} onChange={() => toggleFeat(f)} /> <WikiLink wikiTitle={f} title={f}>{f}</WikiLink>
          </label>)}</div>
        </section>
      </>}

      {mainTab === 'inventory' && <>
        {state ? <>
          <EquippedItemsPanel equipped={state.equipped_items} />
          <DamageEstimatesPanel estimates={state.damage_estimates} />
          <StaticUploadAnalyzer setHoverInfo={setHoverInfo} />
          <InventoryWeightPanel breakdown={state.inventory_weight} setHoverInfo={setHoverInfo} />
        </> : <>
          <section className="gamePanel inventoryWeightPanel"><div className="panelTitle">Inventory</div><p className="referenceNote">Load a save first to see equipped gear, skill damage estimates, PSI ability previews, and read-only inventory weight breakdowns.</p></section>
          <StaticUploadAnalyzer setHoverInfo={setHoverInfo} />
        </>}
      </>}

      {mainTab === 'factions' && <>
        {state ? <section className="gamePanel factionPanel">
          <div className="panelTitle">Faction relation visualizer / Faction hostilities - read only</div>
          <p className="referenceNote">Best-effort scan of saved faction tables in <code>global.dat</code>. This is a warning/inspection panel only; it does not edit faction state. Raw player relation code <b>0</b> is highlighted because it appears on your latest hostile Camp Hathor save, while <b>2</b> matched the earlier non-hostile SortingNightmare save.</p>
          {changedToHostile.length > 0 && <div className="invalidBox">Changed to hostile versus {factionComparison?.baseline_name}: {changedToHostile.map((d:any) => `${d.name} (${d.baseline_value} → ${d.current_value})`).join(', ')}</div>}
          {factionComparison && factionComparison.deltas?.length > 0 && <div className="runtimeReport">Compared against {factionComparison.baseline_name}: {factionComparison.deltas.length} player-relation delta(s). Baseline path: {factionComparison.baseline_path}</div>}
          {hostileFactionRows.length > 0 && <div className="invalidBox">All raw-code-0 factions in this save: {hostileFactionRows.map((f:any) => f.name || f.id).join(', ')}</div>}
          <div className="factionGrid">{factionRows.map((f: any) => <article key={`${f.id}-${f.offset}`} className={'factionCard ' + (f.player_relation?.value === 0 ? 'hostile' : '')} onMouseEnter={() => setHoverInfo({ title: f.name || f.id, kind: 'Faction relation', text: `Raw player relation code ${f.player_relation?.value ?? 'missing'} at payload offset ${f.player_relation?.value_offset ?? 'n/a'}. Parser confidence: ${f.confidence}.` })}>
            <h3>{f.name || f.id}</h3>
            <div className="tag">{f.id}</div>
            <p>Player relation: <b>{f.player_relation ? `${f.player_relation.value} · ${f.player_relation.label}` : 'not found'}</b></p>
            {f.player_relation?.value === 0 && <small>Warning: likely hostile / shoot-on-sight state.</small>}
          </article>)}</div>
        </section> : <section className="gamePanel factionPanel"><div className="panelTitle">Faction hostilities</div><p className="referenceNote">Load a save first to inspect faction hostility markers.</p></section>}

        {state && areaMarkers && <section className="gamePanel factionPanel">
          <div className="panelTitle">Area clear / kill markers - read only</div>
          <p className="referenceNote">Heuristic scan of readable saved script keys in <code>global.dat</code>. This starts decoding prefixes such as <b>loc_</b>, <b>frag_</b>, <b>npc_</b>, <b>xpbl_</b>, and map ids such as <b>cvw47</b>. It is inspection only; values are not edited here.</p>
          {killMarkers.length > 0 && <div className="runtimeReport">Detected {killMarkers.length} kill/death marker(s): {killMarkers.slice(0, 8).map((m:any) => m.text).join(', ')}{killMarkers.length > 8 ? '…' : ''}</div>}
          <div className="factionGrid">{areaRows.map((area: any) => <article key={area.area_id} className={'factionCard ' + (area.kill_markers?.length ? 'hostile' : '')} onMouseEnter={() => setHoverInfo({ title: area.area_label || area.area_id, kind: 'Area markers', text: `${area.markers.length} readable marker(s), ${area.kill_markers.length} kill/death marker(s), ${(area.mapped_factions || []).length} faction hint(s). Prefix and faction meanings are heuristic; value_byte is the raw byte immediately after the serialized key.` })}>
            <h3>{area.area_label || area.area_id}</h3>
            <div className="tag">{area.area_id}</div>
            <p>{area.markers.length} marker(s) · <b>{area.kill_markers.length}</b> kill/death</p>
            {area.mapped_factions?.length > 0 && <p>Faction hints: <b>{area.mapped_factions.slice(0, 4).map((f:any) => `${f.name || f.id} (${f.confidence})`).join(', ')}</b></p>}
            {area.markers.slice(0, 6).map((m:any) => <small key={`${m.text}-${m.offset}`} title={m.after_hex}>{m.text}: value {m.value_byte} · {m.prefix || 'no prefix'} · {m.category}{m.mapped_factions?.length ? ` · factions: ${m.mapped_factions.map((f:any) => `${f.id}/${f.confidence}`).join(', ')}` : ''}</small>)}
          </article>)}</div>
        </section>}
      </>}

      {mainTab === 'qol' && <>
        <section className="gamePanel runtimeModsPanel">
          <div className="panelTitle">Runtime mods - expert live patch tab / QoL patching</div>
          <p className="referenceNote">This tab patches the installed game assembly, not a save. Close Underrail first. The UI checks every few seconds and locks runtime mod controls whenever Underrail is running. Patch actions create a timestamped game assembly backup under <code>underrail_respec_backups</code> and also copy your latest save into repo-local ignored <code>runtime_safety_backups</code> before writing.</p>
          <div className="runtimeControls">
            <input className="pathInput" value={gameDir} onChange={e => setGameDir(e.target.value)} placeholder="Underrail install folder containing underrail.exe" />
            <button onClick={scanRuntimeMods} disabled={hostedStaticMode}>Scan install</button>
            <button onClick={() => refreshRuntimeStatus(true)} disabled={hostedStaticMode}>Check game status</button>
          </div>
          <div className={'runtimeReport ' + (runtimeLocked || hostedStaticMode ? 'locked' : '')}>
            <b>{hostedStaticMode ? 'DISABLED: hosted static mode' : runtimeLocked ? 'LOCKED: Underrail is running' : 'Ready: Underrail not detected'}</b> · {hostedStaticMode ? 'Runtime patching requires the local Python app.' : runtimeStatus?.message}
          </div>
          {runtimeScan && <div className="runtimeReport">
            <div>Assembly: {runtimeScan.assembly}</div>
            <div>SHA256: {runtimeScan.sha256}</div>
            {Object.entries(runtimeScan.mods || {}).map(([id, info]: any) => <div key={id} className="patchPoint"><b>{id}</b>: {info.implemented ? 'implemented' : 'not implemented yet'} · candidates {info.candidate_count} · {info.target || info.details}</div>)}
          </div>}
          <div className="modGrid">
            {[
              ['item_weight', 'Item weight', 'Multiplies Weight and SingleItemWeight getters. Default is 0.1x, which keeps a 250 kg carry load at about 25 kg instead of over-reducing it.'],
              ['force_restock', 'Force restock', 'Forces merchant restock boolean true when barter/restock path runs.'],
              ['traders_buy_all', 'Traders buy all', 'Disables barter item category/quantity restriction methods.'],
              ['fastforward', 'Fastforward (experimental; do not use yet)', 'Known to patch and roll back, but failed live launch smoke testing on build 21973456; kept visible as experimental for future debugging, not part of the stable click-to-patch set.'],
              ['throwing_chance_cap', 'Throwing hit chance cap', 'Changes repeated 0.9 throwing cap constants; already applied on this install.'],
            ].map(([id, title, text]) => <label key={id} className="modCard runtimeToggle">
              <input type="checkbox" checked={!!runtimeModSelection[id]} disabled={hostedStaticMode || runtimeLocked || id === 'fastforward'} onChange={() => toggleRuntimeMod(id)} />
              <h3>{title}</h3>
              <p>{text}</p>
            </label>)}
          </div>
          <div className="modCard runtimeToggle">
            <label>Throw cap <input type="number" min="0.15" max="1" step="0.01" value={throwingCap} disabled={hostedStaticMode || runtimeLocked} onChange={e => setThrowingCap(Number(e.target.value))} /></label>
            <label>Weight x <input type="number" min="0" max="1" step="0.001" value={weightMultiplier} disabled={hostedStaticMode || runtimeLocked} onChange={e => setWeightMultiplier(Number(e.target.value))} /></label>
            <button onClick={() => patchSelectedRuntimeMods(true)} disabled={hostedStaticMode || !gameDir || runtimeLocked}>Dry-run selected</button>
            <button onClick={() => patchSelectedRuntimeMods(false)} disabled={hostedStaticMode || !gameDir || runtimeLocked}>Backup and patch selected</button>
            <button onClick={rollbackRuntimePatch} disabled={hostedStaticMode || !lastRuntimeBackup || runtimeLocked}>Rollback last runtime backup</button>
            {runtimeActionResult && <div className="runtimeReport"><b>Last QoL patch action</b><br />{runtimeActionResult}</div>}
          </div>
        </section>

        {state?.community_mods && <section className="gamePanel communityModsPanel">
          <div className="panelTitle">External modding references</div>
          <p className="referenceNote">Reviewed {state.community_mods.source.name} as runtime IL-hook reference material. Stable entries can be applied only through the separate QoL Patching tab with scan, dry-run, backup, and rollback controls; no third-party mod code or game assets are bundled.</p>
          <div className="modGrid">{state.community_mods.mods.map(m => <article key={m.id} className="modCard" onMouseEnter={() => setHoverInfo({ title: m.name, kind: 'Runtime mod reference', text: `${m.effect} ${m.integration_signal}` })}>
            <h3>{m.name}</h3>
            <div className="tag">{m.category}</div>
            <p>{m.effect}</p>
            {m.default_from_source && <small>Source default: {m.default_from_source}</small>}
          </article>)}</div>
          <p className="referenceNote"><a href={state.community_mods.source.url} target="_blank" rel="noreferrer">Source repository</a> · credited reference material; runtime patching here is independently implemented and guarded by backup/rollback.</p>
        </section>}
      </>}

    </main>
  );
}
