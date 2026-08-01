import React, { useState, useMemo } from "react";
import {
  LayoutDashboard, Users, Inbox, Mail, Settings, Search, ChevronRight,
  CheckCircle2, Circle, AlertCircle, FileText, Upload, Download,
  Send, ArrowLeft, Filter, MoreHorizontal, FolderOpen, Clock
} from "lucide-react";

// ---------------------------------------------------------------------------
// Mock data — mirrors the locked TaxVault spec (DocCodes, categories, AY logic)
// ---------------------------------------------------------------------------

const DOC_LABELS = {
  Form16: "Form 16", AIS: "AIS", "26AS": "26AS", CGSTMT: "Capital Gains Statement",
  DEMAT: "Demat Statement", MFSTMT: "Mutual Fund Statement", HLINT: "Home Loan Interest",
  RENT: "Rent Receipt", "80G": "80G Donation Receipt", "80C": "80C Proof", "80D": "80D Health Insurance",
  NPS: "NPS Statement", BANKSTMT: "Bank Statement",
};

const CATEGORY_DOCS = {
  Salaried: ["Form16"], "Stock Investor": ["CGSTMT", "DEMAT"], "MF Investor": ["MFSTMT"],
  "Home Loan": ["HLINT"], Rental: ["RENT"], Donations: ["80G"], Insurance: ["80C", "80D"],
  NPS: ["NPS"], Business: ["BANKSTMT"],
};

const BASE_DOCS = ["AIS", "26AS"];

function requiredDocsFor(categories) {
  const set = new Set(BASE_DOCS);
  categories.forEach((c) => (CATEGORY_DOCS[c] || []).forEach((d) => set.add(d)));
  return Array.from(set);
}

const CLIENTS = [
  { id: 1, pan: "FGHIJ5678K", name: "Priya Mehta", phone: "98xxxxxx21", categories: ["Salaried", "Stock Investor"], received: ["AIS", "26AS", "Form16"] },
  { id: 2, pan: "ABCDE1234F", name: "Rahul Sharma", phone: "98xxxxxx02", categories: ["Salaried", "Home Loan"], received: ["AIS", "26AS", "Form16", "HLINT"] },
  { id: 3, pan: "KLMNO9988P", name: "Ananya Rao", phone: "97xxxxxx45", categories: ["Business"], received: [] },
  { id: 4, pan: "PQRST4455Q", name: "Vikram Nair", phone: "99xxxxxx11", categories: ["Salaried", "MF Investor", "Insurance"], received: ["AIS", "26AS", "Form16", "MFSTMT", "80C"] },
  { id: 5, pan: "UVWXY7766R", name: "Sneha Iyer", phone: "96xxxxxx88", categories: ["Salaried", "Donations"], received: ["AIS", "26AS"] },
  { id: 6, pan: "ZABCD3322S", name: "Arjun Kapoor", phone: "95xxxxxx33", categories: ["Salaried", "Rental", "Stock Investor"], received: ["AIS", "26AS", "Form16", "RENT", "CGSTMT", "DEMAT"] },
  { id: 7, pan: "EFGHI6611T", name: "Meera Joshi", phone: "94xxxxxx77", categories: ["NPS", "Salaried"], received: ["AIS"] },
  { id: 8, pan: "JKLMN8899U", name: "Devansh Gupta", phone: "93xxxxxx09", categories: ["Business", "Insurance"], received: ["AIS", "26AS", "BANKSTMT", "80D"] },
];

function statusFor(client) {
  const req = requiredDocsFor(client.categories);
  const receivedCount = req.filter((d) => client.received.includes(d)).length;
  if (receivedCount === req.length) return { key: "ready", label: "Ready", receivedCount, total: req.length };
  if (receivedCount === 0) return { key: "not_started", label: "Not Started", receivedCount, total: req.length };
  return { key: "in_progress", label: `In Progress (${receivedCount} of ${req.length})`, receivedCount, total: req.length };
}

const REVIEW_QUEUE = [
  { id: "r1", filename: "IMG_20260722_scan.jpg", reason: "No PAN detected (blurry scan)", detected: "—" },
  { id: "r2", filename: "download (3).pdf", reason: "PAN found, no client match", detected: "NEWPQ2211X" },
  { id: "r3", filename: "statement_final_v2.pdf", reason: "Matched client, DocCode unclear", detected: "FGHIJ5678K" },
  { id: "r4", filename: "WhatsApp Image 2026-07-24.jpeg", reason: "No identifier readable", detected: "—" },
];

const INTAKE_BATCH = [
  { id: "f1", original: "scan0091.pdf", pan: "FGHIJ5678K", client: "Priya Mehta", code: "CGSTMT", renamed: "FGHIJ5678K_CGSTMT_AY26-27_260726.pdf", method: "OCR", status: "filed" },
  { id: "f2", original: "Form16_2026.pdf", pan: "ABCDE1234F", client: "Rahul Sharma", code: "Form16", renamed: "ABCDE1234F_Form16_AY26-27_260726.pdf", method: "Text", status: "filed" },
  { id: "f3", original: "AIS_download.pdf", pan: "PQRST4455Q", client: "Vikram Nair", code: "AIS", renamed: "PQRST4455Q_AIS_AY26-27_260726.pdf", method: "Text", status: "filed" },
  { id: "f4", original: "HDFC_stmt_apr-mar.pdf", pan: "ZABCD3322S", client: "Arjun Kapoor", code: "BANKSTMT", renamed: "ZABCD3322S_BANKSTMT_AY26-27_260726.pdf", method: "Text", status: "filed" },
  { id: "f5", original: "IMG_20260722_scan.jpg", pan: "—", client: "—", code: "—", renamed: "—", method: "OCR", status: "review" },
  { id: "f6", original: "download (3).pdf", pan: "NEWPQ2211X", client: "No match", code: "—", renamed: "—", method: "Text", status: "review" },
  { id: "f7", original: "80C_LIC_receipt.pdf", pan: "PQRST4455Q", client: "Vikram Nair", code: "80C", renamed: "PQRST4455Q_80C_AY26-27_260726.pdf", method: "Text", status: "filed" },
  { id: "f8", original: "statement_final_v2.pdf", pan: "FGHIJ5678K", client: "Priya Mehta", code: "MISC", renamed: "FGHIJ5678K_MISC_AY26-27_260726.pdf", method: "OCR", status: "misc" },
];

// ---------------------------------------------------------------------------
// Small UI atoms
// ---------------------------------------------------------------------------

const STATUS_STYLE = {
  ready: { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-200", dot: "bg-emerald-500" },
  in_progress: { bg: "bg-amber-50", text: "text-amber-700", ring: "ring-amber-200", dot: "bg-amber-500" },
  not_started: { bg: "bg-rose-50", text: "text-rose-700", ring: "ring-rose-200", dot: "bg-rose-500" },
};

function StatusPill({ status }) {
  const s = STATUS_STYLE[status.key];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${s.bg} ${s.text} ${s.ring}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {status.label}
    </span>
  );
}

function NavItem({ icon: Icon, label, active, onClick, count }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
        active ? "bg-white/10 text-white font-medium" : "text-slate-300 hover:bg-white/5 hover:text-white"
      }`}
    >
      <Icon size={17} strokeWidth={2} />
      <span className="flex-1 text-left">{label}</span>
      {count != null && (
        <span className={`rounded-full px-1.5 py-0.5 text-[11px] ${active ? "bg-white/20 text-white" : "bg-white/10 text-slate-300"}`}>
          {count}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Screens
// ---------------------------------------------------------------------------

function Dashboard({ clients, onOpenClient, ay }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

  const counts = useMemo(() => {
    const c = { ready: 0, in_progress: 0, not_started: 0 };
    clients.forEach((cl) => (c[statusFor(cl).key] += 1));
    return c;
  }, [clients]);

  const filtered = clients.filter((c) => {
    const st = statusFor(c).key;
    const matchesFilter = filter === "all" || st === filter;
    const matchesQuery = c.name.toLowerCase().includes(query.toLowerCase()) || c.pan.toLowerCase().includes(query.toLowerCase());
    return matchesFilter && matchesQuery;
  });

  return (
    <div className="flex-1 overflow-auto">
      <div className="border-b border-slate-200 bg-white px-8 py-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Client Dashboard</h1>
            <p className="mt-0.5 text-sm text-slate-500">Assessment Year {ay} &middot; {clients.length} clients</p>
          </div>
          <button className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">
            <Send size={15} /> Send Initial Requests
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 px-8 pt-6">
        {[
          { key: "ready", label: "Ready for ITR", value: counts.ready, icon: CheckCircle2, tint: "text-emerald-600 bg-emerald-50" },
          { key: "in_progress", label: "In Progress", value: counts.in_progress, icon: Clock, tint: "text-amber-600 bg-amber-50" },
          { key: "not_started", label: "Not Started", value: counts.not_started, icon: AlertCircle, tint: "text-rose-600 bg-rose-50" },
        ].map((card) => (
          <button
            key={card.key}
            onClick={() => setFilter(filter === card.key ? "all" : card.key)}
            className={`rounded-xl border p-4 text-left transition-all ${
              filter === card.key ? "border-slate-900 ring-1 ring-slate-900" : "border-slate-200 hover:border-slate-300"
            } bg-white`}
          >
            <div className="flex items-center justify-between">
              <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${card.tint}`}>
                <card.icon size={17} />
              </span>
              <span className="text-2xl font-semibold text-slate-900">{card.value}</span>
            </div>
            <p className="mt-3 text-sm font-medium text-slate-600">{card.label}</p>
          </button>
        ))}
      </div>

      <div className="mx-8 mt-6 rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-3.5">
          <div className="relative flex-1 max-w-xs">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name or PAN..."
              className="w-full rounded-lg border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-slate-300 focus:bg-white"
            />
          </div>
          {filter !== "all" && (
            <button onClick={() => setFilter("all")} className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-500 hover:bg-slate-50">
              <Filter size={12} /> Clear filter
            </button>
          )}
          <span className="ml-auto text-xs text-slate-400">{filtered.length} shown</span>
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="px-5 py-2.5 font-medium">Client</th>
              <th className="px-5 py-2.5 font-medium">PAN</th>
              <th className="px-5 py-2.5 font-medium">Categories</th>
              <th className="px-5 py-2.5 font-medium">Status</th>
              <th className="px-5 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => {
              const st = statusFor(c);
              return (
                <tr key={c.id} onClick={() => onOpenClient(c)} className="cursor-pointer border-b border-slate-50 last:border-0 hover:bg-slate-50">
                  <td className="px-5 py-3 font-medium text-slate-800">{c.name}</td>
                  <td className="px-5 py-3 font-mono text-xs text-slate-500">{c.pan}</td>
                  <td className="px-5 py-3">
                    <div className="flex flex-wrap gap-1">
                      {c.categories.map((cat) => (
                        <span key={cat} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{cat}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-5 py-3"><StatusPill status={st} /></td>
                  <td className="px-5 py-3 text-right"><ChevronRight size={15} className="text-slate-300" /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="h-8" />
    </div>
  );
}

function ClientVault({ client, onBack, ay }) {
  const required = requiredDocsFor(client.categories);
  const status = statusFor(client);

  return (
    <div className="flex-1 overflow-auto">
      <div className="border-b border-slate-200 bg-white px-8 py-5">
        <button onClick={onBack} className="mb-3 flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700">
          <ArrowLeft size={14} /> Back to dashboard
        </button>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-slate-900">{client.name}</h1>
              <StatusPill status={status} />
            </div>
            <p className="mt-1 font-mono text-xs text-slate-500">{client.pan} &middot; {client.phone}</p>
          </div>
          <div className="flex gap-2">
            <button className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
              <Download size={13} /> Download All
            </button>
            <button className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800">
              <Send size={13} /> Send Reminder
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6 px-8 py-6">
        <div className="col-span-2 rounded-xl border border-slate-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Required Documents &mdash; AY {ay}</h2>
            <span className="text-xs text-slate-400">{status.receivedCount} of {status.total} received</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-slate-900 transition-all" style={{ width: `${(status.receivedCount / status.total) * 100}%` }} />
          </div>
          <div className="mt-5 divide-y divide-slate-50">
            {required.map((code) => {
              const got = client.received.includes(code);
              return (
                <div key={code} className="flex items-center gap-3 py-2.5">
                  {got ? <CheckCircle2 size={17} className="text-emerald-500" /> : <Circle size={17} className="text-slate-300" />}
                  <span className={`text-sm ${got ? "text-slate-700" : "text-slate-400"}`}>{DOC_LABELS[code] || code}</span>
                  <span className="font-mono text-[11px] text-slate-300">{code}</span>
                  {got && (
                    <span className="ml-auto font-mono text-[11px] text-slate-400">
                      {client.pan}_{code}_AY{ay.replace("20", "")}_260726.pdf
                    </span>
                  )}
                  {!got && <span className="ml-auto text-[11px] font-medium text-rose-400">Missing</span>}
                </div>
              );
            })}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">Category Tags</h3>
            <div className="flex flex-wrap gap-1.5">
              {client.categories.map((c) => (
                <span key={c} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">{c}</span>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
              <FolderOpen size={15} className="text-slate-400" /> Vault Path
            </h3>
            <p className="break-all font-mono text-[11px] leading-relaxed text-slate-500">
              /Vault/{client.pan}_{client.name.replace(/\s/g, "")}/AY{ay.replace("20", "")}/
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">Reminder History</h3>
            <p className="text-xs text-slate-400">No reminders sent yet for AY {ay}.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewQueue() {
  return (
    <div className="flex-1 overflow-auto">
      <div className="border-b border-slate-200 bg-white px-8 py-6">
        <h1 className="text-xl font-semibold text-slate-900">Review Queue</h1>
        <p className="mt-0.5 text-sm text-slate-500">{REVIEW_QUEUE.length} files need manual attention &mdash; unmatched, unclassified, or unreadable</p>
      </div>
      <div className="mx-8 mt-6 space-y-3">
        {REVIEW_QUEUE.map((item) => (
          <div key={item.id} className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
              <FileText size={16} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-800">{item.filename}</p>
              <p className="mt-0.5 text-xs text-slate-400">{item.reason} &middot; detected: <span className="font-mono">{item.detected}</span></p>
            </div>
            <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
              Assign Client
            </button>
            <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
              Set DocType
            </button>
          </div>
        ))}
      </div>
      <div className="h-8" />
    </div>
  );
}

function IntakeScreen() {
  const [phase, setPhase] = useState("idle"); // idle | processing | done
  const [ay, setAy] = useState("AY 2026-27");

  function startProcessing() {
    setPhase("processing");
    // single reliable timer — CSS handles the visual progress animation
    setTimeout(() => setPhase("done"), 1600);
  }

  const filed = INTAKE_BATCH.filter((f) => f.status === "filed");
  const misc = INTAKE_BATCH.filter((f) => f.status === "misc");
  const review = INTAKE_BATCH.filter((f) => f.status === "review");

  // group filed+misc docs by client for the folder tree
  const byClient = {};
  [...filed, ...misc].forEach((f) => {
    if (!byClient[f.client]) byClient[f.client] = { pan: f.pan, files: [] };
    byClient[f.client].files.push(f);
  });

  return (
    <div className="flex-1 overflow-auto">
      <div className="border-b border-slate-200 bg-white px-8 py-6">
        <h1 className="text-xl font-semibold text-slate-900">Document Intake</h1>
        <p className="mt-0.5 text-sm text-slate-500">Point at a folder of mixed documents &mdash; TaxVault reads, matches, classifies, and files each one.</p>
      </div>

      <div className="px-8 py-6">
        {phase === "idle" && (
          <div className="rounded-xl border-2 border-dashed border-slate-300 bg-white p-10 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100">
              <Upload size={20} className="text-slate-500" />
            </div>
            <p className="mt-4 text-sm font-medium text-slate-700">Drop a folder here, or click to browse</p>
            <p className="mt-1 text-xs text-slate-400">Accepts up to 700 mixed files &middot; PDF, JPG, PNG</p>

            <div className="mx-auto mt-6 flex max-w-xs items-center gap-2">
              <label className="text-xs font-medium text-slate-500">Assessment Year</label>
              <select value={ay} onChange={(e) => setAy(e.target.value)} className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs">
                <option>AY 2026-27</option>
                <option>AY 2025-26 (belated)</option>
              </select>
            </div>

            <button onClick={startProcessing} className="mt-6 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-800">
              Select "Downloads" Folder &middot; 8 files found (demo)
            </button>
          </div>
        )}

        {phase === "processing" && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
            <p className="text-sm font-medium text-slate-700">Processing batch for {ay}&hellip;</p>
            <div className="mx-auto mt-4 h-2 w-full max-w-md overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-sky-500"
                style={{ width: "100%", transition: "width 1.5s linear", animation: "none" }}
                ref={(el) => { if (el) requestAnimationFrame(() => { el.style.width = "0%"; requestAnimationFrame(() => { el.style.width = "100%"; }); }); }}
              />
            </div>
            <p className="mt-3 text-xs text-slate-400">Extracting text, matching identifiers, classifying and filing&hellip;</p>
            <button onClick={() => setPhase("done")} className="mt-5 text-xs font-medium text-sky-400 hover:underline">
              View Results &rarr;
            </button>
          </div>
        )}

        {phase === "done" && (
          <>
            <div className="grid grid-cols-4 gap-4">
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-2xl font-semibold text-slate-900">{INTAKE_BATCH.length}</p>
                <p className="mt-1 text-xs text-slate-500">Files processed</p>
              </div>
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                <p className="text-2xl font-semibold text-emerald-700">{filed.length}</p>
                <p className="mt-1 text-xs text-emerald-600">Filed automatically</p>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-2xl font-semibold text-amber-700">{misc.length}</p>
                <p className="mt-1 text-xs text-amber-600">Filed as MISC</p>
              </div>
              <div className="rounded-xl border border-rose-200 bg-rose-50 p-4">
                <p className="text-2xl font-semibold text-rose-700">{review.length}</p>
                <p className="mt-1 text-xs text-rose-600">Sent to Review Queue</p>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-5 gap-6">
              {/* Results table */}
              <div className="col-span-3 rounded-xl border border-slate-200 bg-white">
                <div className="border-b border-slate-100 px-5 py-3">
                  <h2 className="text-sm font-semibold text-slate-800">Processing Results</h2>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-100 text-left uppercase tracking-wide text-slate-400">
                      <th className="px-5 py-2 font-medium">Original File</th>
                      <th className="px-3 py-2 font-medium">Matched Client</th>
                      <th className="px-3 py-2 font-medium">DocCode</th>
                      <th className="px-3 py-2 font-medium">Method</th>
                      <th className="px-3 py-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {INTAKE_BATCH.map((f) => (
                      <tr key={f.id} className="border-b border-slate-50 last:border-0">
                        <td className="max-w-[140px] truncate px-5 py-2.5 font-mono text-slate-500" title={f.original}>{f.original}</td>
                        <td className="px-3 py-2.5 text-slate-700">{f.client}</td>
                        <td className="px-3 py-2.5">
                          {f.code !== "—" ? <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10.5px] text-slate-600">{f.code}</span> : "—"}
                        </td>
                        <td className="px-3 py-2.5 text-slate-400">{f.method}</td>
                        <td className="px-3 py-2.5">
                          {f.status === "filed" && <span className="flex items-center gap-1 text-emerald-600"><CheckCircle2 size={12} /> Filed</span>}
                          {f.status === "misc" && <span className="flex items-center gap-1 text-amber-600"><AlertCircle size={12} /> MISC</span>}
                          {f.status === "review" && <span className="flex items-center gap-1 text-rose-500"><Inbox size={12} /> Review</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Vault folder tree */}
              <div className="col-span-2 rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <FolderOpen size={15} className="text-slate-400" /> Resulting /Vault/ structure
                </h2>
                <div className="space-y-3 font-mono text-[11px]">
                  {Object.entries(byClient).map(([name, info]) => (
                    <div key={name}>
                      <p className="text-slate-600">
                        <span className="text-slate-400">/Vault/</span>{info.pan}_{name.replace(/\s/g, "")}
                        <span className="text-slate-400">/</span>
                      </p>
                      <p className="ml-4 text-slate-500">
                        <span className="text-slate-400">AY26-27/</span>
                      </p>
                      <div className="ml-8 mt-1 space-y-0.5 border-l border-slate-100 pl-3">
                        {info.files.map((f) => (
                          <p key={f.id} className={f.status === "misc" ? "text-amber-600" : "text-slate-500"}>
                            {f.renamed}
                          </p>
                        ))}
                      </div>
                    </div>
                  ))}
                  <div>
                    <p className="text-slate-400">/Review/</p>
                    <div className="ml-4 mt-1 space-y-0.5 border-l border-slate-100 pl-3">
                      {review.map((f) => (
                        <p key={f.id} className="text-rose-500">{f.original} <span className="text-slate-300">(unmodified)</span></p>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <button onClick={() => setPhase("idle")} className="mt-6 text-xs font-medium text-slate-500 hover:text-slate-700">
              &larr; Process another batch
            </button>
          </>
        )}
      </div>
      <div className="h-8" />
    </div>
  );
}

function Placeholder({ label }) {
  return (
    <div className="flex flex-1 items-center justify-center text-sm text-slate-400">
      {label} &mdash; not part of this POC
    </div>
  );
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------

export default function TaxVaultPOC() {
  const [view, setView] = useState("dashboard");
  const [activeClient, setActiveClient] = useState(null);
  const AY = "2026-27";

  const nav = [
    { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { key: "intake", label: "Document Intake", icon: Upload },
    { key: "clients", label: "Clients", icon: Users, count: CLIENTS.length },
    { key: "review", label: "Review Queue", icon: Inbox, count: REVIEW_QUEUE.length },
    { key: "reminders", label: "Reminders", icon: Mail },
    { key: "settings", label: "Settings", icon: Settings },
  ];

  function openClient(c) {
    setActiveClient(c);
    setView("client");
  }

  return (
    <div className="flex h-[720px] w-full overflow-hidden rounded-2xl border border-slate-800 bg-slate-50 font-sans shadow-xl">
      {/* Sidebar */}
      <div className="flex w-56 shrink-0 flex-col bg-slate-950 p-4">
        <div className="mb-6 flex items-center gap-2 px-1">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-sky-500 text-xs font-bold text-white">TV</div>
          <span className="text-sm font-bold tracking-wide text-white">TaxVault</span>
        </div>
        <div className="space-y-1">
          {nav.map((n) => (
            <NavItem
              key={n.key}
              icon={n.icon}
              label={n.label}
              count={n.count}
              active={view === n.key || (n.key === "clients" && view === "dashboard") || (n.key === "clients" && view === "client")}
              onClick={() => {
                if (n.key === "clients") setView("dashboard");
                else setView(n.key);
              }}
            />
          ))}
        </div>
        <div className="mt-auto rounded-lg bg-white/5 p-3">
          <p className="text-[11px] font-medium text-slate-300">Firm Admin</p>
          <p className="mt-0.5 text-xs text-white">Jeet &middot; Demo Firm</p>
        </div>
      </div>

      {/* Content */}
      {view === "dashboard" && <Dashboard clients={CLIENTS} onOpenClient={openClient} ay={AY} />}
      {view === "intake" && <IntakeScreen />}
      {view === "client" && activeClient && <ClientVault client={activeClient} onBack={() => setView("dashboard")} ay={AY} />}
      {view === "review" && <ReviewQueue />}
      {view === "reminders" && <Placeholder label="Reminders screen" />}
      {view === "settings" && <Placeholder label="Settings screen" />}
    </div>
  );
}
