import { Fragment, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { IconButton } from '../design/components';
import { useAppState } from '../state/AppState';
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
                {data.columns.map((col) => (
                  <th key={col} className="micro-label">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, rowIndex) => (
                <Fragment key={rowIndex}>
                  <tr
                    className={styles.row}
                    onClick={() => setExpandedRow(expandedRow === rowIndex ? null : rowIndex)}
                  >
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
                      <td colSpan={data.columns.length} className={styles.expandedCell}>
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
              ))}
            </tbody>
          </table>
        ) : (
          <div className={styles.empty}>표시할 데이터 없음</div>
        )}
      </div>
    </div>
  );
}
