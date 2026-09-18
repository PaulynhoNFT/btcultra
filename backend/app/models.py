from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, BigInteger, Double, Integer,
    ForeignKey, UniqueConstraint, Index, JSON, func, text
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, declared_attr
from app.database import Base


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        Index("idx_candles_symbol_tf_time", "symbol", "timeframe", "timestamp"),
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle_unique"),
    )

    timestamp = Column(DateTime(timezone=True), primary_key=True)
    symbol = Column(Text, primary_key=True)
    timeframe = Column(Text, primary_key=True)
    open = Column(Double, nullable=False)
    high = Column(Double, nullable=False)
    low = Column(Double, nullable=False)
    close = Column(Double, nullable=False)
    volume = Column(Double, nullable=False)
    source = Column(Text, nullable=False, default="ccxt")
    is_final = Column(Boolean, nullable=False, default=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrderbookL2(Base):
    __tablename__ = "orderbook_l2"
    __table_args__ = (
        Index("idx_orderbook_symbol_time", "symbol", "timestamp"),
    )

    timestamp = Column(DateTime(timezone=True), primary_key=True)
    symbol = Column(Text, primary_key=True)
    exchange = Column(Text, primary_key=True)
    bids = Column(JSONB, nullable=False)
    asks = Column(JSONB, nullable=False)
    sequence = Column(BigInteger, nullable=False)


class DerivativesData(Base):
    __tablename__ = "derivatives_data"
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "timestamp", name="uq_deriv_unique"),
    )

    timestamp = Column(DateTime(timezone=True), primary_key=True)
    symbol = Column(Text, primary_key=True)
    exchange = Column(Text, primary_key=True)
    funding_rate = Column(Double)
    open_interest = Column(Double)
    mark_price = Column(Double)
    index_price = Column(Double)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("idx_signals_symbol_time", "symbol", "timestamp"),
        Index("idx_signals_ok_time", "ok", "timestamp"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(Text, nullable=False)
    timeframe = Column(Text, nullable=False)
    side = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    ok = Column(Boolean, nullable=False)
    entry_price = Column(Double, nullable=False)
    stop_price = Column(Double, nullable=False)
    tp1 = Column(Double, nullable=False)
    tp2 = Column(Double, nullable=False)
    tp3 = Column(Double, nullable=False)
    rr = Column(Double, nullable=False)
    mode = Column(Text, nullable=False)
    engine_version = Column(Text, nullable=False)
    score_version = Column(Text, nullable=False)
    risk_version = Column(Text, nullable=False)
    snapshot_hash = Column(Text, nullable=False)
    snapshot_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    snapshot = relationship("SignalSnapshot", back_populates="signal", uselist=False)
    shadow = relationship("ShadowPortfolio", back_populates="signal", uselist=False)


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"

    signal_id = Column(PG_UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True)
    tf1_indicators = Column(JSONB, nullable=False)
    tf2_indicators = Column(JSONB, nullable=False)
    tf3_indicators = Column(JSONB, nullable=False)
    regime_report = Column(JSONB, nullable=False)
    correction_report = Column(JSONB, nullable=False)
    trigger_report = Column(JSONB, nullable=False)
    score_breakdown = Column(JSONB, nullable=False)
    derivatives_ctx = Column(JSONB)
    news_blackout = Column(Boolean, nullable=False, default=False)
    candle_hashes = Column(JSONB, nullable=False)
    ipfs_cid = Column(Text)

    signal = relationship("Signal", back_populates="snapshot")


class ShadowPortfolio(Base):
    __tablename__ = "shadow_portfolio"
    __table_args__ = (
        Index("idx_shadow_signal", "signal_id"),
        Index("idx_shadow_outcome", "outcome"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    signal_id = Column(PG_UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), nullable=False)
    block_reason = Column(Text, nullable=False)
    entry_price = Column(Double, nullable=False)
    stop_price = Column(Double, nullable=False)
    tp1 = Column(Double, nullable=False)
    tp2 = Column(Double, nullable=False)
    tp3 = Column(Double, nullable=False)
    rr = Column(Double, nullable=False)
    score = Column(Integer, nullable=False)
    outcome = Column(Text)
    pnl_r = Column(Double)
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    signal = relationship("Signal", back_populates="shadow")


class WeightsHistory(Base):
    __tablename__ = "weights_history"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    version = Column(Text, nullable=False)
    weights = Column(JSONB, nullable=False)
    feature_importance = Column(JSONB, nullable=False)
    trained_on_from = Column(DateTime(timezone=True), nullable=False)
    trained_on_to = Column(DateTime(timezone=True), nullable=False)
    n_signals = Column(Integer, nullable=False)
    oos_sharpe = Column(Double)
    oos_pbo = Column(Double)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    totp_secret = Column(Text)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    plan = Column(Text, nullable=False, default="free")
    quota_daily = Column(Integer, nullable=False, default=100)
    quota_monthly = Column(Integer, nullable=False, default=1000)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(timezone=True))

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("UserApiKey", back_populates="user", cascade="all, delete-orphan")
    paper_trades = relationship("PaperTrade", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("idx_refresh_user", "user_id"),
        Index("idx_refresh_expires", "expires_at"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="refresh_tokens")


class UserApiKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (
        Index("idx_user_exchange_active", "user_id", "exchange", postgresql_where=text("is_active = true")),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    exchange = Column(Text, nullable=False)
    api_key_enc = Column(Text, nullable=False)
    api_secret_enc = Column(Text, nullable=False)
    passphrase_enc = Column(Text)
    label = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    permissions = Column(JSONB, nullable=False, default={"read": True, "trade": False})
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="api_keys")


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    __table_args__ = (
        Index("idx_paper_user", "user_id", "created_at"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    signal_id = Column(PG_UUID(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL"))
    symbol = Column(Text, nullable=False)
    side = Column(Text, nullable=False)
    entry_price = Column(Double, nullable=False)
    stop_price = Column(Double, nullable=False)
    tp1 = Column(Double, nullable=False)
    tp2 = Column(Double, nullable=False)
    tp3 = Column(Double, nullable=False)
    size_usd = Column(Double, nullable=False)
    leverage = Column(Integer, nullable=False, default=1)
    status = Column(Text, nullable=False, default="open")
    pnl_r = Column(Double)
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="paper_trades")


class EconomicEvent(Base):
    __tablename__ = "economic_events"
    __table_args__ = (
        Index("idx_econ_time", "event_time"),
        Index("idx_econ_currency_impact", "currency", "impact", "event_time"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_name = Column(Text, nullable=False)
    country = Column(Text, nullable=False)
    currency = Column(Text, nullable=False)
    impact = Column(Text, nullable=False)
    forecast = Column(Text)
    previous = Column(Text)
    event_time = Column(DateTime(timezone=True), nullable=False)
    actual = Column(Text)
    source = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EngineMetric(Base):
    __tablename__ = "engine_metrics"
    __table_args__ = (
        Index("idx_metrics_name_time", "metric_name", "timestamp"),
    )

    timestamp = Column(DateTime(timezone=True), primary_key=True)
    metric_name = Column(Text, primary_key=True)
    metric_value = Column(Double, nullable=False)
    labels = Column(JSONB, nullable=False, default={})


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_time", "timestamp"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    prev_hash = Column(Text, nullable=False)
    curr_hash = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
