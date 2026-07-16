'use client';

import { useMemo, useState } from 'react';

type AttrName = 'Strength'|'Dexterity'|'Agility'|'Constitution'|'Perception'|'Will'|'Intelligence';
type SaveInfo = { name: string; path: string; modified?: string; modified_ts?: number };
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
};

type HoverInfo = { title: string; text: string; kind?: string } | null;

const API = process.env.NEXT_PUBLIC_UNDERAIL_API || 'http://127.0.0.1:8765';
const ATTRS: AttrName[] = ['Strength','Dexterity','Agility','Constitution','Perception','Will','Intelligence'];
const SKILLS = ['Guns','Heavy Guns','Throwing','Crossbows','Melee','Dodge','Evasion','Stealth','Hacking','Lockpicking','Pickpocketing','Traps','Mechanics','Electronics','Chemistry','Biology','Tailoring','Thought Control','Psychokinesis','Metathermics','Temporal Manipulation','Persuasion','Intimidation','Mercantile'];
const SKILL_GROUPS = [
  ['Guns','Heavy Guns','Throwing','Crossbows','Melee'],
  ['Dodge','Evasion','Stealth','Hacking','Lockpicking','Pickpocketing','Traps'],
  ['Mechanics','Electronics','Chemistry','Biology','Tailoring'],
  ['Thought Control','Psychokinesis','Metathermics','Temporal Manipulation'],
  ['Persuasion','Intimidation','Mercantile'],
];

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
    <button
      type="button"
      className={'statCard ' + (value !== current ? 'changed' : '')}
      onMouseEnter={() => setHoverInfo({ title: name, text: tip, kind })}
      onFocus={() => setHoverInfo({ title: name, text: tip, kind })}
    >
      <span className="statName">{name}</span>
      <span className="stepper" onClick={(e) => { e.stopPropagation(); onChange(Math.max(kind === 'Base attribute' ? 1 : 0, value - 1)); }}>−</span>
      <input value={value} onChange={e => onChange(Number(e.target.value || 0))} onClick={e => e.stopPropagation()} />
      <span className="stepper" onClick={(e) => { e.stopPropagation(); onChange(value + 1); }}>+</span>
      <span className="effective">{bonus ? `eff ${effective}` : ''}</span>
    </button>
  );
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
  const [message, setMessage] = useState('Start the Python backend on port 8765, then list or load a save.');
  const [validation, setValidation] = useState<any>(null);

  const featList = useMemo(() => state ? Array.from(new Set([...(state.all_known_feats || []), ...(state.detected_feats || [])])).sort() : [], [state]);

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

  const attrTotal = Object.values(attrs).reduce((a,b) => a + b, 0);
  const skillTotal = Object.values(skills).reduce((a,b) => a + b, 0);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">Local save editor</div>
          <h1>Underrail Visual Respec Editor</h1>
        </div>
        <div className="statusPill">Python API: {API}</div>
      </header>

      <section className="loadPanel gamePanel">
        <div className="pathRow">
          <input className="pathInput" value={savePath} onChange={e => setSavePath(e.target.value)} placeholder="Save folder or global.dat path" />
          <button onClick={() => loadSave()}>Load</button>
          <button onClick={listSaves}>List saves</button>
          <select value={sort} onChange={e => setSort(e.target.value)}>
            <option value="modified">Newest first</option>
            <option value="alpha">A → Z</option>
            <option value="modified_asc">Oldest first</option>
          </select>
        </div>
        {saves.length > 0 && <div className="saveGrid">{saves.map(s => <button key={s.path} onClick={() => loadSave(s.path)}><b>{s.name}</b><span>{s.modified}</span></button>)}</div>}
        <div className="message">{message}</div>
      </section>

      <div className="layout">
        <section className="gamePanel characterPanel">
          <div className="panelTitle">Base abilities</div>
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
          <div className="panelTitle">Budgets</div>
          <label>Level <input type="number" value={level} onChange={e => setLevel(Number(e.target.value))} /></label>
          <label>Attr budget <input type="number" value={attrBudget} onChange={e => setAttrBudget(Number(e.target.value))} /></label>
          <label>Skill budget <input type="number" value={skillBudget} onChange={e => setSkillBudget(Number(e.target.value))} /></label>
          <label className="check"><input type="checkbox" checked={ignoreBudget} onChange={e => setIgnoreBudget(e.target.checked)} /> Ignore point budget</label>
          <button className="wide" onClick={validate} disabled={!state}>Validate build</button>
          <label>New save <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="JetSki-Respec" /></label>
          <button className="wide" onClick={createRespec} disabled={!state || !newName}>Create cloned save</button>
          {validation && <div className={validation.valid ? 'validBox' : 'invalidBox'}>{validation.valid ? 'Valid' : 'Blocked'}<br />{validation.issues?.map((x:any) => <div key={x.message}>{x.message}</div>)}</div>}
        </section>
      </div>

      <section className="gamePanel featsPanel">
        <div className="panelTitle">Feats to protect / validate</div>
        <div className="featGrid">{featList.map(f => <label key={f} onMouseEnter={() => setHoverInfo({ title: f, kind: 'Feat', text: state?.tooltips.feats[f] || '' })}>
          <input type="checkbox" checked={selectedFeats.has(f)} onChange={() => toggleFeat(f)} /> {f}
        </label>)}</div>
      </section>
    </main>
  );
}
