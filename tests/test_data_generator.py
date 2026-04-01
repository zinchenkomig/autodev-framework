"""Tests for data degradation generator."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.data_generator import (
    DataGenerator,
    DegradationError,
    DegradationPattern,
    SecurityError,
    SecurityValidator,
    ValidationError,
)
from autodev.core.models import (
    DegradationBackup,
    DegradationConfig,
    DegradationMode,
    DegradationOperation,
    DegradationStatus,
    DegradationType,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestDegradationEnums:
    """Test degradation-related enums."""

    def test_degradation_mode_values(self):
        assert DegradationMode.APPEND == "append"
        assert DegradationMode.REPLACE == "replace"

    def test_degradation_type_values(self):
        assert DegradationType.SPIKE == "spike"
        assert DegradationType.DROP == "drop"
        assert DegradationType.NOISE == "noise"
        assert DegradationType.MISSING == "missing"
        assert DegradationType.DRIFT == "drift"

    def test_degradation_status_values(self):
        assert DegradationStatus.PENDING == "pending"
        assert DegradationStatus.RUNNING == "running"
        assert DegradationStatus.COMPLETED == "completed"
        assert DegradationStatus.FAILED == "failed"
        assert DegradationStatus.ROLLED_BACK == "rolled_back"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestDegradationModels:
    """Test degradation-related models."""

    def test_degradation_config_creation(self):
        config = DegradationConfig(
            id=uuid.uuid4(),
            name="Test Config",
            target_database="test_db",
            target_table="metrics",
            target_columns=["cpu_usage", "memory_usage"],
            degradation_type=DegradationType.SPIKE,
            degradation_mode=DegradationMode.APPEND,
            severity=Decimal("0.8"),
            created_by="test_user",
        )

        assert config.name == "Test Config"
        assert config.target_database == "test_db"
        assert config.target_table == "metrics"
        assert config.target_columns == ["cpu_usage", "memory_usage"]
        assert config.degradation_type == DegradationType.SPIKE
        assert config.degradation_mode == DegradationMode.APPEND
        assert config.severity == Decimal("0.8")
        assert config.created_by == "test_user"

    def test_degradation_operation_creation(self):
        config_id = uuid.uuid4()
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(hours=1)

        operation = DegradationOperation(
            id=uuid.uuid4(),
            config_id=config_id,
            start_time=start_time,
            end_time=end_time,
            performed_by="test_user",
        )

        assert operation.config_id == config_id
        assert operation.start_time == start_time
        assert operation.end_time == end_time
        assert operation.performed_by == "test_user"
        assert operation.status == DegradationStatus.PENDING

    def test_degradation_backup_creation(self):
        operation_id = uuid.uuid4()
        backup = DegradationBackup(
            id=uuid.uuid4(),
            operation_id=operation_id,
            table_name="metrics",
            record_id="test_record_123",
            column_name="cpu_usage",
            original_value="50.0",
            new_value="150.0",
            data_type="float",
        )

        assert backup.operation_id == operation_id
        assert backup.table_name == "metrics"
        assert backup.record_id == "test_record_123"
        assert backup.column_name == "cpu_usage"
        assert backup.original_value == "50.0"
        assert backup.new_value == "150.0"
        assert backup.data_type == "float"


# ---------------------------------------------------------------------------
# Degradation Pattern tests
# ---------------------------------------------------------------------------


class TestDegradationPattern:
    """Test degradation pattern generation."""

    def test_generate_spike(self):
        original = 100.0
        severity = 0.5
        result = DegradationPattern.generate_spike(original, severity)

        # Spike should increase the value significantly
        assert result > original
        assert result >= original * 2  # At least 2x with 50% severity

    def test_generate_drop(self):
        original = 100.0
        severity = 0.5
        result = DegradationPattern.generate_drop(original, severity)

        # Drop should decrease the value
        assert result < original
        assert result >= 0  # Should not go negative

    def test_generate_noise(self):
        original = 100.0
        severity = 0.1
        result = DegradationPattern.generate_noise(original, severity)

        # Noise should be close to original with small variation
        assert abs(result - original) <= original * severity * 2

    def test_generate_drift(self):
        original = 100.0
        severity = 0.2
        trend = 1.0
        result = DegradationPattern.generate_drift(original, severity, trend)

        # Drift should increase the value
        assert result > original

    def test_generate_missing(self):
        result = DegradationPattern.generate_missing()
        assert result is None

    def test_generate_anomaly_spike(self):
        result = DegradationPattern.generate_anomaly(
            DegradationType.SPIKE, 100.0, 0.5
        )
        assert result > 100.0

    def test_generate_anomaly_missing(self):
        result = DegradationPattern.generate_anomaly(
            DegradationType.MISSING, 100.0, 0.5
        )
        assert result is None

    def test_generate_anomaly_invalid_type(self):
        result = DegradationPattern.generate_anomaly("invalid", 100.0, 0.5)
        # Should return original value for unknown types
        assert result == 100.0

    def test_generate_anomaly_non_numeric(self):
        result = DegradationPattern.generate_anomaly(
            DegradationType.SPIKE, "not_a_number", 0.5
        )
        # Should return original value for non-numeric inputs
        assert result == "not_a_number"

    def test_generate_anomaly_none_input(self):
        result = DegradationPattern.generate_anomaly(
            DegradationType.SPIKE, None, 0.5
        )
        assert result is None


# ---------------------------------------------------------------------------
# Security Validator tests
# ---------------------------------------------------------------------------


class TestSecurityValidator:
    """Test security validation functionality."""

    def test_validate_database_access_allowed(self):
        # Should not raise exception for allowed databases
        SecurityValidator.validate_database_access("warehouse")
        SecurityValidator.validate_database_access("metrics")
        SecurityValidator.validate_database_access("test_db")

    def test_validate_database_access_denied(self):
        with pytest.raises(SecurityError):
            SecurityValidator.validate_database_access("forbidden_db")

    def test_validate_table_access_allowed(self):
        # Should not raise exception for allowed tables
        SecurityValidator.validate_table_access("metrics")
        SecurityValidator.validate_table_access("events")

    def test_validate_table_access_denied(self):
        with pytest.raises(SecurityError):
            SecurityValidator.validate_table_access("users")
        with pytest.raises(SecurityError):
            SecurityValidator.validate_table_access("auth")
        with pytest.raises(SecurityError):
            SecurityValidator.validate_table_access("secrets")

    def test_validate_time_range_valid(self):
        start = datetime.now(UTC)
        end = start + timedelta(hours=1)
        # Should not raise exception for valid range
        SecurityValidator.validate_time_range(start, end)

    def test_validate_time_range_invalid_order(self):
        start = datetime.now(UTC)
        end = start - timedelta(hours=1)
        with pytest.raises(ValidationError):
            SecurityValidator.validate_time_range(start, end)

    def test_validate_time_range_too_long(self):
        start = datetime.now(UTC)
        end = start + timedelta(days=400)  # Exceeds maximum
        with pytest.raises(ValidationError):
            SecurityValidator.validate_time_range(start, end)

    def test_validate_operation_size_valid(self):
        # Should not raise exception for valid size
        SecurityValidator.validate_operation_size(1000)

    def test_validate_operation_size_too_large(self):
        with pytest.raises(ValidationError):
            SecurityValidator.validate_operation_size(20000)  # Exceeds maximum

    def test_validate_columns_valid(self):
        # Should not raise exception for valid columns
        SecurityValidator.validate_columns(["cpu_usage", "memory_usage"])
        SecurityValidator.validate_columns(["metric-name", "metric_value"])

    def test_validate_columns_invalid_characters(self):
        with pytest.raises(ValidationError):
            SecurityValidator.validate_columns(["cpu_usage; DROP TABLE"])
        with pytest.raises(ValidationError):
            SecurityValidator.validate_columns(["invalid column"])

    def test_validate_columns_too_long(self):
        long_column = "a" * 100  # Exceeds 64 character limit
        with pytest.raises(ValidationError):
            SecurityValidator.validate_columns([long_column])


# ---------------------------------------------------------------------------
# Data Generator tests
# ---------------------------------------------------------------------------


class TestDataGenerator:
    """Test DataGenerator functionality."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock(spec=AsyncSession)
        session.get_bind.return_value = AsyncMock()
        return session

    @pytest.fixture
    def mock_config(self):
        return DegradationConfig(
            id=uuid.uuid4(),
            name="Test Config",
            target_database="warehouse",
            target_table="metrics",
            target_columns=["cpu_usage"],
            degradation_type=DegradationType.SPIKE,
            degradation_mode=DegradationMode.APPEND,
            severity=Decimal("0.5"),
            created_by="test_user",
        )

    @pytest.fixture
    def data_generator(self, mock_session):
        return DataGenerator(mock_session)

    def test_init(self, mock_session):
        generator = DataGenerator(mock_session, "postgresql://test")
        assert generator.session == mock_session
        assert generator.target_db_url == "postgresql://test"

    @pytest.mark.asyncio
    async def test_get_target_engine_valid_database(self, data_generator):
        engine = await data_generator.get_target_engine("warehouse")
        assert engine is not None

    @pytest.mark.asyncio
    async def test_get_target_engine_invalid_database(self, data_generator):
        with pytest.raises(SecurityError):
            await data_generator.get_target_engine("forbidden_db")

    @pytest.mark.asyncio
    async def test_create_degradation_security_validation(self, data_generator, mock_session):
        # Test with forbidden database
        config = DegradationConfig(
            id=uuid.uuid4(),
            name="Bad Config",
            target_database="forbidden_db",
            target_table="metrics",
            target_columns=["cpu_usage"],
            degradation_type=DegradationType.SPIKE,
            degradation_mode=DegradationMode.APPEND,
            severity=Decimal("0.5"),
            created_by="test_user",
        )

        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(hours=1)

        with pytest.raises(SecurityError):
            await data_generator.create_degradation(
                config, start_time, end_time, "test_user", dry_run=True
            )

    @pytest.mark.asyncio
    @patch("autodev.core.data_generator.DataGenerator._execute_append_mode")
    async def test_create_degradation_append_mode(self, mock_append, data_generator, mock_config):
        mock_append.return_value = None
        data_generator.session.add = MagicMock()
        data_generator.session.flush = AsyncMock()
        data_generator.session.commit = AsyncMock()

        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(hours=1)

        operation = await data_generator.create_degradation(
            mock_config, start_time, end_time, "test_user", dry_run=True
        )

        assert operation.config_id == mock_config.id
        assert operation.performed_by == "test_user"
        assert operation.status == DegradationStatus.COMPLETED
        mock_append.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_append_records(self, data_generator, mock_config):
        operation = DegradationOperation(
            id=uuid.uuid4(),
            config_id=mock_config.id,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(hours=2),
            performed_by="test_user",
        )

        records = await data_generator._generate_append_records(operation, mock_config)

        assert len(records) > 0
        assert all("id" in record for record in records)
        assert all(mock_config.time_column in record for record in records)
        assert all("cpu_usage" in record for record in records)
        assert all(record["source"] == "degradation_generator" for record in records)

    @pytest.mark.asyncio
    async def test_rollback_operation_validation_errors(self, data_generator):
        # Test with non-existent operation
        data_generator.session.get = AsyncMock(return_value=None)

        with pytest.raises(ValidationError, match="Operation .* not found"):
            await data_generator.rollback_operation(uuid.uuid4(), "test_user")

        # Test with wrong status
        operation = DegradationOperation(
            id=uuid.uuid4(),
            config_id=uuid.uuid4(),
            status=DegradationStatus.FAILED,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(hours=1),
            performed_by="test_user",
        )
        data_generator.session.get = AsyncMock(return_value=operation)

        with pytest.raises(ValidationError, match="Cannot rollback operation with status"):
            await data_generator.rollback_operation(operation.id, "test_user")

    @pytest.mark.asyncio
    async def test_rollback_operation_append_mode_error(self, data_generator):
        operation = DegradationOperation(
            id=uuid.uuid4(),
            config_id=uuid.uuid4(),
            status=DegradationStatus.COMPLETED,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(hours=1),
            performed_by="test_user",
        )

        config = DegradationConfig(
            id=operation.config_id,
            name="Test",
            target_database="warehouse",
            target_table="metrics",
            target_columns=["cpu_usage"],
            degradation_mode=DegradationMode.APPEND,
            created_by="test_user",
        )

        data_generator.session.get = AsyncMock(side_effect=[operation, config])

        with pytest.raises(ValidationError, match="Rollback only supported for replace mode"):
            await data_generator.rollback_operation(operation.id, "test_user")


# ---------------------------------------------------------------------------
# API Routes tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDataGeneratorAPI:
    """Test data generator API endpoints."""

    def test_degradation_config_create_dto_validation(self):
        from autodev.api.routes.data_generator import DegradationConfigCreateDTO

        # Valid data
        dto = DegradationConfigCreateDTO(
            name="Test Config",
            target_database="warehouse",
            target_table="metrics",
            target_columns=["cpu_usage", "memory_usage"],
        )
        assert dto.name == "Test Config"
        assert dto.target_columns == ["cpu_usage", "memory_usage"]

    def test_degradation_config_create_dto_validation_errors(self):
        from autodev.api.routes.data_generator import DegradationConfigCreateDTO

        # Invalid severity
        with pytest.raises(ValueError):
            DegradationConfigCreateDTO(
                name="Test",
                target_database="warehouse",
                target_table="metrics",
                target_columns=["cpu_usage"],
                severity=1.5,  # > 1.0
            )

        # Empty target_columns
        with pytest.raises(ValueError):
            DegradationConfigCreateDTO(
                name="Test",
                target_database="warehouse",
                target_table="metrics",
                target_columns=[],
            )

    def test_degradation_execute_dto_validation(self):
        from autodev.api.routes.data_generator import DegradationExecuteDTO

        config_id = uuid.uuid4()
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(hours=1)

        dto = DegradationExecuteDTO(
            config_id=config_id,
            start_time=start_time,
            end_time=end_time,
        )

        assert dto.config_id == config_id
        assert dto.start_time == start_time
        assert dto.end_time == end_time
        assert dto.dry_run is False

    def test_degradation_execute_dto_time_validation(self):
        from autodev.api.routes.data_generator import DegradationExecuteDTO

        config_id = uuid.uuid4()
        start_time = datetime.now(UTC)
        end_time = start_time - timedelta(hours=1)  # Invalid: before start

        with pytest.raises(ValueError, match="end_time must be after start_time"):
            DegradationExecuteDTO(
                config_id=config_id,
                start_time=start_time,
                end_time=end_time,
            )

    def test_degradation_execute_dto_timezone_validation(self):
        from autodev.api.routes.data_generator import DegradationExecuteDTO

        config_id = uuid.uuid4()
        naive_datetime = datetime.now()  # No timezone

        with pytest.raises(ValueError, match="Datetime must be timezone-aware"):
            DegradationExecuteDTO(
                config_id=config_id,
                start_time=naive_datetime,
                end_time=naive_datetime + timedelta(hours=1),
            )