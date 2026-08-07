"use client";

/**
 * The catalog overview: triage inbox, catalog map, and the zone map.
 *
 * `/investigate` answers "why did this break". This page answers what you
 * actually ask first — what is the state of everything, and which of these
 * should I pick up. Rows deep-link into an investigation so the two views are one
 * workflow rather than two features.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import CatalogMap, { CatalogNodeDetail } from "@/components/CatalogMap";
import { Panel } from "@/components/panels";
import ZoneMap from "@/components/ZoneMap";
import {
  LIVE_CATALOG_AVAILABLE,
  apiBaseFor,
  type Catalog,
} from "@/lib/useInvestigation";
import {
  SIGNAL_LABELS,
  humaniseHours,
  type CatalogMap as CatalogMapData,
  type CatalogNode,
  type Health,
  type InboxEntry,
} from "@/lib/types";

type SortKey = "overdue" | "downstream" | "name";

export default function OverviewPage() {
  const [catalog, setCatalog] = useState<Catalog>("demo");
  const [health, setHealth] = useState<Health | null>(null);
  const [inbox, setInbox] = useState<InboxEntry[] | null>(null);
  const [map, setMap] = useState<CatalogMapData | null>(null);
  const [failed, setFailed] = useState(false);
  const [sort, setSort] = useState<SortKey>("overdue");
  const [inspected, setInspected] = useState<CatalogNode | null>(null);

  const load = useCallback(async (which: Catalog) => {
    const base = apiBaseFor(which);
    setInbox(null);
    setMap(null);
    setFailed(false);
    setInspected(null);
    try {
      const [healthRes, inboxRes, mapRes] = await Promise.all([
        fetch(`${base}/api/health`),
        fetch(`${base}/api/inbox`),
        fetch(`${base}/api/catalog`),
      ]);
      if (!inboxRes.ok || !mapRes.ok) throw new Error("bad response");
      setHealth(healthRes.ok ? await healthRes.json() : null);
      setInbox(await inboxRes.json());
      setMap(await mapRes.json());
    } catch {
      // These views need a backend; there is no recorded fallback for them, so
      // say so rather than showing an empty table that looks like "all clear".
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load(catalog);
  }, [catalog, load]);

  const sorted = useMemo(() => {
    if (!inbox) return [];
    const rows = [...inbox];
    if (sort === "name") rows.sort((a, b) => a.name.localeCompare(b.name));
    else if (sort === "downstream")
      rows.sort((a, b) => b.downstream_count - a.downstream_count);
    else rows.sort((a, b) => (b.overdue_ratio ?? 0) - (a.overdue_ratio ?? 0));
    return rows;
  }, [inbox, sort]);

  const showZones = catalog === "live";

  return (
    <div className="mx-auto max-w-[1180px] px-5 pb-24 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-4 py-6">
        <div className="flex items-baseline gap-4">
          <Link href="/" className="text-lg font-semibold tracking-tight text-bone no-underline">
            Cauzon
          </Link>
          <span className="hidden text-xs text-muted sm:inline">catalog overview</span>
        </div>
        <Link
          href="/investigate"
          className="border border-jade-dim bg-jade-dim/25 px-3 py-2 text-[11px] font-semibold tracking-[0.12em] text-jade uppercase no-underline hover:bg-jade-dim/45"
        >
          Investigate
        </Link>
      </header>

      <main id="main" className="space-y-4">
        {LIVE_CATALOG_AVAILABLE && (
          <div role="group" aria-label="Catalog" className="flex flex-wrap gap-2">
            {(
              [
                { id: "demo" as Catalog, label: "Demo catalog" },
                { id: "live" as Catalog, label: "Live public catalog" },
              ]
            ).map((option) => (
              <button
                key={option.id}
                onClick={() => setCatalog(option.id)}
                aria-pressed={catalog === option.id}
                className={`flex-1 border px-4 py-3 text-[12px] font-semibold tracking-[0.1em] uppercase transition-colors ${
                  catalog === option.id
                    ? "border-jade-dim bg-jade-dim/25 text-jade"
                    : "border-line text-bone-dim hover:border-line-bright"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}

        {failed && (
          <Panel title="Overview unavailable">
            <p className="prose-evidence m-0">
              These views read the catalog directly, so they need the backend. The
              recorded replay covers an investigation, not a whole-catalog
              inventory — showing an empty table here would read as{" "}
              <em>all clear</em>, which would be worse than saying nothing.{" "}
              <Link href="/investigate" className="text-jade no-underline">
                The investigation view still works.
              </Link>
            </p>
          </Panel>
        )}

        {/* ---- triage inbox ---------------------------------------------- */}
        {inbox && (
          <Panel
            title="Triage inbox"
            aside={
              <span className="label">
                {inbox.length} open ·{" "}
                {inbox.filter((e) => e.severity === "critical").length} critical
              </span>
            }
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="label">Sort</span>
              {(
                [
                  ["overdue", "Most overdue"],
                  ["downstream", "Most at stake"],
                  ["name", "Name"],
                ] as [SortKey, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setSort(key)}
                  aria-pressed={sort === key}
                  className={`border px-2 py-1 text-[10px] tracking-[0.1em] uppercase transition-colors ${
                    sort === key
                      ? "border-jade-dim text-jade"
                      : "border-line text-muted hover:border-line-bright"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {inbox.length === 0 ? (
              <p className="prose-evidence m-0">
                Nothing is past its freshness SLA right now.
              </p>
            ) : (
              <ul className="m-0 list-none space-y-0 p-0">
                {sorted.map((entry) => (
                  <InboxRow key={entry.urn} entry={entry} catalog={catalog} />
                ))}
              </ul>
            )}
          </Panel>
        )}

        {/* ---- catalog map ----------------------------------------------- */}
        {map && (
          <Panel
            title="Catalog map"
            aside={
              <span className="label">
                {map.counts.total} assets · {map.counts.incident} with incidents
              </span>
            }
          >
            <CatalogMap
              data={map}
              onSelect={setInspected}
              selectedUrn={inspected?.urn ?? null}
            />
            {inspected && <CatalogNodeDetail node={inspected} />}
            <p className="prose-evidence m-0 mt-3 text-muted">
              Laid out by depth, so every asset draws to the right of what it
              depends on — upstream is a direction here, not something to trace.
              Amber is an open incident, oxide carries a signal without one.
            </p>
          </Panel>
        )}

        {/* ---- zone map: only meaningful for the live catalog -------------
            Gated on the inbox having loaded, not just on `!failed`. The
            geometry is local, so it would otherwise render the instant you
            switch catalogs and then vanish when the fetch turns out to have
            failed — and its caption talks about "that stale lookup table",
            which is only true once we have actually read the catalog. */}
        {showZones && inbox && (
          <Panel title="What the stale lookup actually covers">
            <ZoneMap
              stale={Boolean(
                inbox?.some((e) => e.name.toLowerCase().includes("taxi zones")),
              )}
              apiBase={apiBaseFor("live")}
            />
          </Panel>
        )}

        {!inbox && !failed && (
          <Panel title="Loading">
            <p className="prose-evidence m-0">Reading the catalog…</p>
          </Panel>
        )}
      </main>

      <footer className="rule mt-12 flex flex-wrap items-center justify-between gap-4 pt-5">
        <span className="label">
          {health?.live_source
            ? `Live from ${health.live_source.name}`
            : "Apache-2.0 · built on the DataHub MCP server"}
        </span>
        <a
          href="https://github.com/bkd-dotcom/cauzon"
          className="text-xs text-bone-dim no-underline hover:text-jade"
        >
          Source
        </a>
      </footer>
    </div>
  );
}

function InboxRow({
  entry,
  catalog,
}: {
  entry: InboxEntry;
  catalog: Catalog;
}) {
  const tone =
    entry.severity === "critical"
      ? "border-oxide-dim text-oxide"
      : entry.severity === "overdue"
        ? "border-amber-dim text-amber"
        : "border-line text-bone-dim";
  return (
    <li className="rule py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className={`border px-2 py-0.5 text-[10px] tracking-[0.1em] uppercase ${tone}`}
        >
          {entry.severity}
        </span>
        <span className="text-[13px] font-medium text-bone">{entry.name}</span>
        {entry.overdue_ratio !== null && entry.overdue_ratio > 1 && (
          <span className="label" title="How many times past its own freshness SLA">
            {entry.overdue_ratio}× SLA
          </span>
        )}
        {entry.freshness_hours !== null && (
          <span className="label">{humaniseHours(entry.freshness_hours)} old</span>
        )}
        {entry.downstream_count > 0 && (
          <span className="label text-bone-dim">
            {entry.downstream_count} downstream
          </span>
        )}
        {entry.owner && <span className="text-[11px] text-muted">{entry.owner}</span>}
        <Link
          href={{
            pathname: "/investigate",
            query: { urn: entry.urn, ...(catalog === "live" ? { catalog } : {}) },
          }}
          className="ml-auto shrink-0 text-[10px] tracking-[0.1em] text-jade uppercase no-underline hover:underline"
        >
          Investigate →
        </Link>
      </div>
      {(entry.failed_assertion || entry.signals.length > 0) && (
        <p className="prose-evidence m-0 mt-1 text-[13px]">
          {entry.failed_assertion}
          {entry.signals.length > 0 && (
            <span className="text-muted">
              {entry.failed_assertion ? " · " : ""}
              {entry.signals.map((s) => SIGNAL_LABELS[s]).join(", ")}
            </span>
          )}
        </p>
      )}
    </li>
  );
}
