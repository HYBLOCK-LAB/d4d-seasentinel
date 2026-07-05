import { Fragment, useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import type * as GeoJSON from 'geojson';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppDispatch, useAppState } from '../state/AppState';
import { api } from '../api/client';
import styles from './OntologyPanel.module.css';

const PAGE_SIZE = 50;

interface TableInfo {
  table: string;
  count: number;
}

interface RowsResponse {
  columns: string[];
  rows: unknown[][];
  total: number;
}

interface RenderedCell {
  text: string;
  title: string;
  muted: boolean;
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function isGeometryish(value: string): boolean {
  return (
    /"type"\s*:\s*"(Point|LineString|Polygon|MultiPoint|MultiLineString|MultiPolygon|GeometryCollection)"/.test(
      value,
    ) || /"coordinates"\s*:/.test(value)
  );
}

function isGeometryType(type: unknown): type is GeoJSON.Geometry['type'] {
  return (
    type === 'Point' ||
    type === 'LineString' ||
    type === 'Polygon' ||
    type === 'MultiPoint' ||
    type === 'MultiLineString' ||
    type === 'MultiPolygon' ||
    type === 'GeometryCollection'
  );
}

function parseFeature(value: unknown): GeoJSON.Feature | null {
  let parsed = value;
  if (typeof value === 'string') {
    if (!isGeometryish(value)) return null;
    try {
      parsed = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const obj = parsed as Record<string, unknown>;
  if (obj.type === 'Feature' && obj.geometry && typeof obj.geometry === 'object') {
    return parsed as GeoJSON.Feature;
  }
  if (obj.type === 'FeatureCollection' && Array.isArray(obj.features)) {
    return (obj.features.find(Boolean) as GeoJSON.Feature | undefined) ?? null;
  }
  if (isGeometryType(obj.type)) {
    return { type: 'Feature', geometry: obj as unknown as GeoJSON.Geometry, properties: {} };
  }
  return null;
}

function collectCoordinates(value: unknown, acc: Array<[number, number]>): void {
  if (!Array.isArray(value)) return;
  if (
    value.length >= 2 &&
    typeof value[0] === 'number' &&
    typeof value[1] === 'number' &&
    Number.isFinite(value[0]) &&
    Number.isFinite(value[1])
  ) {
    acc.push([value[0], value[1]]);
    return;
  }
  value.forEach((item) => collectCoordinates(item, acc));
}

function collectGeometryCoordinates(geometry: GeoJSON.Geometry, acc: Array<[number, number]>): void {
  if (geometry.type === 'GeometryCollection') {
    geometry.geometries.forEach((item) => collectGeometryCoordinates(item, acc));
    return;
  }
  collectCoordinates(geometry.coordinates, acc);
}

function centroidOf(feature: GeoJSON.Feature): { lon: number; lat: number } | null {
  const geometry = feature.geometry;
  if (!geometry) return null;
  const points: Array<[number, number]> = [];
  collectGeometryCoordinates(geometry, points);
  if (!points.length) return null;
  const [lon, lat] = points.reduce(([sx, sy], [x, y]) => [sx + x, sy + y], [0, 0]);
  return { lon: lon / points.length, lat: lat / points.length };
}

function renderCell(value: unknown): RenderedCell {
  if (value === null || value === undefined) {
    return { text: '·', title: '', muted: true };
  }
  if (typeof value === 'object') {
    const json = JSON.stringify(value);
    if (isGeometryish(json)) {
      return { text: '⌖ geom', title: json, muted: false };
    }
    return { text: truncate(json, 40), title: json, muted: false };
  }
  if (typeof value === 'string') {
    if (isGeometryish(value)) {
      return { text: '⌖ geom', title: value, muted: false };
    }
    return { text: truncate(value, 60), title: value, muted: false };
  }
  return { text: String(value), title: String(value), muted: false };
}

export function OntologyPanel() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const focus = state.ontologyFocus;

  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<RowsResponse | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [chipDismissed, setChipDismissed] = useState(false);

  useEffect(() => {
    api.ontologyTables().then((list) => {
      setTables(list);
      setSelectedTable((current) => current || (list[0]?.table ?? ''));
    });
  }, []);

  useEffect(() => {
    if (focus?.table) {
      setSelectedTable(focus.table);
      setOffset(0);
      setChipDismissed(false);
    }
  }, [focus]);

  useEffect(() => {
    if (!selectedTable) {
      setData(null);
      return;
    }
    setExpandedRow(null);
    api.ontologyRows(selectedTable, PAGE_SIZE, offset).then(setData);
  }, [selectedTable, offset]);

  const total = data?.total ?? 0;
  const rangeEnd = Math.min(offset + PAGE_SIZE, total);
  const showChip = Boolean(focus?.srcId) && !chipDismissed && focus?.table === selectedTable;

  function featureForRow(row: unknown[]): GeoJSON.Feature | null {
    const feature = row.map(parseFeature).find((item): item is GeoJSON.Feature => Boolean(item));
    if (!feature) return null;
    return {
      ...feature,
      properties: {
        ...(feature.properties ?? {}),
        table: selectedTable,
      },
    };
  }

  function handleMapClick(event: MouseEvent<HTMLButtonElement>, feature: GeoJSON.Feature) {
    event.stopPropagation();
    const centroid = centroidOf(feature);
    if (!centroid) return;
    dispatch({ type: 'focus', target: centroid });
    dispatch({ type: 'highlight', feature });
  }

  return (
    <div className={styles.panel}>
      <div className={styles.controls}>
        <select
          className={`${styles.select} mono`}
          value={selectedTable}
          onChange={(event) => {
            setSelectedTable(event.target.value);
            setOffset(0);
          }}
        >
          {tables.map((item) => (
            <option key={item.table} value={item.table}>
              {`${item.table} (${item.count})`}
            </option>
          ))}
        </select>
        <div className={styles.pagination}>
          <IconButton title="이전" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            <ChevronLeft size={14} />
          </IconButton>
          <span className={`${styles.pageLabel} mono micro-label`}>
            {total > 0 ? `${offset}–${rangeEnd} / ${total}` : '0 / 0'}
          </span>
          <IconButton title="다음" onClick={() => setOffset(offset + PAGE_SIZE)}>
            <ChevronRight size={14} />
          </IconButton>
        </div>
      </div>
      {showChip ? (
        <div className={styles.chipRow}>
          <span className={`${styles.chip} mono`}>{`근거 원본 ID: ${focus?.srcId}`}</span>
          <IconButton title="닫기" onClick={() => setChipDismissed(true)}>
            <X size={12} />
          </IconButton>
        </div>
      ) : null}
      <div className={styles.tableWrap}>
        {data && data.rows.length > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                <th className="micro-label">지도</th>
                {data.columns.map((col) => (
                  <th key={col} className="micro-label">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, rowIndex) => {
                const feature = featureForRow(row);
                return (
                  <Fragment key={rowIndex}>
                    <tr
                      className={styles.row}
                      onClick={() => setExpandedRow(expandedRow === rowIndex ? null : rowIndex)}
                    >
                      <td className={styles.mapCell}>
                        {feature ? (
                          <button
                            type="button"
                            className={styles.mapButton}
                            onClick={(event) => handleMapClick(event, feature)}
                          >
                            지도
                          </button>
                        ) : (
                          <span className={styles.muted}>·</span>
                        )}
                      </td>
                      {row.map((cell, cellIndex) => {
                        const rendered = renderCell(cell);
                        return (
                          <td
                            key={cellIndex}
                            className={`mono ${rendered.muted ? styles.muted : ''}`}
                            title={rendered.title}
                          >
                            {rendered.text}
                          </td>
                        );
                      })}
                    </tr>
                    {expandedRow === rowIndex ? (
                      <tr>
                        <td colSpan={data.columns.length + 1} className={styles.expandedCell}>
                          <pre className={`${styles.expandedPre} mono`}>
                            {JSON.stringify(
                              Object.fromEntries(data.columns.map((col, i) => [col, row[i]])),
                              null,
                              2,
                            )}
                          </pre>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className={styles.empty}>표시할 데이터 없음</div>
        )}
      </div>
    </div>
  );
}
