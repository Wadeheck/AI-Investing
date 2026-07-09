export interface FormulaInfo {
  version: number;
  trades_learned?: number;
  fitted?: boolean;
  weights: Record<string, number>;
  gain: number;
  entry_threshold: number;
  size_scale?: number;
  stop_loss?: number;
  take_profit?: number;
}

export interface PositionRow {
  symbol: string;
  qty: number;
  avg_price: number;
  price: number;
  value: number;
  pnl: number;
}

export interface DecisionRow {
  symbol: string;
  direction: string;
  score: number;
  confidence: number;
  expected_return?: number;
  rationale: string;
}

export interface StateData {
  ts: string;
  mode: string;
  halted: boolean;
  equity: number;
  cash: number;
  briefing: string;
  formula: FormulaInfo;
  positions: PositionRow[];
  decisions: DecisionRow[];
}

export interface HistoryPoint {
  ts: string;
  equity: number;
  cash: number;
  version: number;
  trades_learned: number;
}

export interface HistoryData {
  updated: string;
  points: HistoryPoint[];
}

export interface BacktestWindow {
  window: number;
  train_end: number;
  val_end: number;
  default_sharpe: number;
  challenger_sharpe: number;
}

export interface BacktestData {
  updated: string;
  provider: string;
  assets: string[];
  adopted: boolean | null;
  dsr?: number | null;
  n_trials?: number | null;
  windows: BacktestWindow[];
  metrics_default: Record<string, number>;
  metrics_chosen: Record<string, number>;
  equity_curve_default: number[];
  equity_curve_chosen: number[];
  formula: FormulaInfo;
}

export interface DashboardData {
  state: StateData | null;
  history: HistoryData | null;
  backtest: BacktestData | null;
}
