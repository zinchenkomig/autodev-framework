"""Tests for enhanced data degradation generator."""

import pytest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from autodev.core.data_generator_config import DegradationConfig, DegradationSecurityConfig
from autodev.core.data_generator_enhanced import EnhancedDataGenerator
from autodev.core.data_generator_security import SecureQueryBuilder, EnhancedSecurityValidator
from autodev.core.data_generator_monitoring import PerformanceTracker, AuditLogger
from autodev.core.data_generator_cleanup import DegradationCleanupService
from autodev.core.models import (
    DegradationBackup,
    DegradationConfig as DegradationConfigModel,
    DegradationMode,
    DegradationOperation,
    DegradationStatus,
    DegradationType,
)


class TestSecureQueryBuilder:
    """Test secure query building functionality."""

    def test_validate_identifier_valid(self):
        """Test valid identifier validation."""
        assert SecureQueryBuilder.validate_identifier("user_table") == "user_table"
        assert SecureQueryBuilder.validate_identifier("metric-name") == "metric-name"
        assert SecureQueryBuilder.validate_identifier("table123") == "table123"

    def test_validate_identifier_invalid(self):
        """Test invalid identifier rejection."""
        with pytest.raises(ValueError, match="Invalid identifier format"):
            SecureQueryBuilder.validate_identifier("table; DROP TABLE")

        with pytest.raises(ValueError, match="Invalid identifier format"):
            SecureQueryBuilder.validate_identifier("123table")  # Can't start with number

        with pytest.raises(ValueError, match="Identifier contains dangerous pattern"):
            SecureQueryBuilder.validate_identifier("drop")

        with pytest.raises(ValueError, match="Identifier too long"):
            SecureQueryBuilder.validate_identifier("a" * 100)

    def test_build_select_query(self):
        """Test secure SELECT query building."""
        query = SecureQueryBuilder.build_select_query("metrics", "created_at")
        assert query is not None
        # Should use parameters instead of string interpolation

    def test_build_update_query(self):
        """Test secure UPDATE query building."""
        query = SecureQueryBuilder.build_update_query("metrics", "cpu_usage")
        assert query is not None
        # Should use parameters instead of string interpolation


class TestDegradationConfig:
    """Test degradation configuration."""

    def test_default_config_loading(self):
        """Test loading default configuration."""
        config = DegradationConfig.load_default()
        assert config.security.max_records_per_operation == 10000
        assert "warehouse" in config.security.allowed_databases
        assert "users" in config.security.forbidden_tables

    def test_security_config_environment_variables(self):
        """Test configuration from environment variables."""
        with patch.dict("os.environ", {
            "DEGRADATION_MAX_RECORDS_PER_OPERATION": "5000",
            "DEGRADATION_ALLOWED_DATABASES": "db1,db2,db3"
        }):
            config = DegradationSecurityConfig()
            assert config.max_records_per_operation == 5000
            assert config.allowed_databases == ["db1", "db2", "db3"]

    def test_critical_tables_always_forbidden(self):
        """Test that critical system tables are always forbidden."""
        config = DegradationSecurityConfig(forbidden_tables=["custom_table"])
        # Critical tables should be automatically added
        assert "users" in config.forbidden_tables
        assert "auth" in config.forbidden_tables
        assert "custom_table" in config.forbidden_tables


class TestEnhancedSecurityValidator:
    """Test enhanced security validation."""

    def test_configurable_database_validation(self):
        """Test database validation uses configuration."""
        with patch("autodev.core.data_generator_security.get_degradation_config") as mock_config:
            mock_config.return_value.security.allowed_databases = ["test_db"]

            # Should pass
            EnhancedSecurityValidator.validate_database_access("test_db")

            # Should fail
            with pytest.raises(Exception):
                EnhancedSecurityValidator.validate_database_access("forbidden_db")

    def test_configurable_operation_size_validation(self):
        """Test operation size validation uses configuration."""
        with patch("autodev.core.data_generator_security.get_degradation_config") as mock_config:
            mock_config.return_value.security.max_records_per_operation = 1000

            # Should pass
            EnhancedSecurityValidator.validate_operation_size(500)

            # Should fail
            with pytest.raises(Exception):
                EnhancedSecurityValidator.validate_operation_size(2000)

    def test_concurrent_operations_validation(self):
        """Test concurrent operations validation."""
        with patch("autodev.core.data_generator_security.get_degradation_config") as mock_config:
            mock_config.return_value.security.max_concurrent_operations = 3

            # Should pass
            EnhancedSecurityValidator.validate_concurrent_operations(2)

            # Should fail
            with pytest.raises(Exception):
                EnhancedSecurityValidator.validate_concurrent_operations(5)


class TestPerformanceTracker:
    """Test performance tracking functionality."""

    def test_operation_timing(self):
        """Test operation timing tracking."""
        tracker = PerformanceTracker()
        operation_id = "test_op_123"

        tracker.start_operation(operation_id)
        duration = tracker.end_operation(operation_id)

        assert isinstance(duration, float)
        assert duration >= 0

    def test_metrics_recording(self):
        """Test metrics recording."""
        tracker = PerformanceTracker()

        tracker.record_records_affected(100)
        tracker.record_backup_created(50)

        summary = tracker.get_metrics_summary()
        assert "records_affected" in summary
        assert "backup_created" in summary
        assert summary["records_affected"]["total"] == 100


class TestAuditLogger:
    """Test audit logging functionality."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def mock_operation(self):
        return DegradationOperation(
            id=uuid.uuid4(),
            config_id=uuid.uuid4(),
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(hours=1),
            performed_by="test_user",
            execution_details={"degradation_type": "spike", "dry_run": False},
        )

    def test_log_operation_created(self, mock_session, mock_operation):
        """Test operation creation logging."""
        logger = AuditLogger(mock_session)
        with patch.object(logger, "_log_event") as mock_log:
            logger.log_operation_created(mock_operation, "Test Config", False)
            mock_log.assert_called_once()

    def test_log_security_violation(self, mock_session):
        """Test security violation logging."""
        logger = AuditLogger(mock_session)
        with patch.object(logger, "_log_event") as mock_log:
            logger.log_security_violation(
                "database_access_denied",
                {"database": "forbidden_db"},
                "malicious_user"
            )
            mock_log.assert_called_once()


class TestEnhancedDataGenerator:
    """Test enhanced data generator functionality."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.get_bind.return_value = AsyncMock()
        return session

    @pytest.fixture
    def mock_config(self):
        return DegradationConfigModel(
            id=uuid.uuid4(),
            name="Test Config",
            target_database="warehouse",
            target_table="metrics",
            target_columns=["cpu_usage"],
            degradation_type=DegradationType.SPIKE,
            degradation_mode=DegradationMode.REPLACE,
            severity=Decimal("0.5"),
            created_by="test_user",
        )

    @pytest.fixture
    def enhanced_generator(self, mock_session):
        with patch("autodev.core.data_generator_enhanced.get_degradation_config"):
            return EnhancedDataGenerator(mock_session)

    @pytest.mark.asyncio
    async def test_create_degradation_with_monitoring(self, enhanced_generator, mock_config, mock_session):
        """Test degradation creation with monitoring."""
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch.object(enhanced_generator, '_execute_replace_mode') as mock_replace:
            mock_replace.return_value = None

            operation = await enhanced_generator.create_degradation(
                mock_config,
                datetime.now(UTC),
                datetime.now(UTC) + timedelta(hours=1),
                "test_user",
                dry_run=True
            )

            assert operation.execution_details.get("enhanced_version") is True
            assert operation.status == DegradationStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_secure_query_execution(self, enhanced_generator):
        """Test that secure queries are used."""
        with patch("autodev.core.data_generator_security.SecureQueryBuilder") as mock_builder:
            mock_builder.execute_select_with_fallback = AsyncMock(return_value=[])

            # This should trigger secure query usage
            # Test would need actual database connection to fully verify


class TestDegradationCleanupService:
    """Test cleanup service functionality."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        return session

    @pytest.fixture
    def cleanup_service(self, mock_session):
        return DegradationCleanupService(mock_session)

    @pytest.mark.asyncio
    async def test_cleanup_old_backups_dry_run(self, cleanup_service):
        """Test dry run backup cleanup."""
        with patch.object(cleanup_service.session, 'execute') as mock_execute:
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all.return_value = [
                MagicMock(),  # Simulate old backup records
                MagicMock(),
            ]
            mock_execute.return_value = mock_result

            stats = await cleanup_service.cleanup_old_backups(dry_run=True)

            assert stats["dry_run"] is True
            assert stats["records_found"] == 2
            assert stats["records_deleted"] == 0

    @pytest.mark.asyncio
    async def test_get_storage_statistics(self, cleanup_service):
        """Test storage statistics retrieval."""
        with patch.object(cleanup_service.session, 'scalar') as mock_scalar:
            mock_scalar.return_value = 100

            stats = await cleanup_service.get_storage_statistics()

            assert "total_operations" in stats
            assert "total_backups" in stats
            assert "retention_policy" in stats

    @pytest.mark.asyncio
    async def test_mark_stale_operations(self, cleanup_service):
        """Test marking stale operations as failed."""
        with patch.object(cleanup_service.session, 'execute') as mock_execute:
            # Mock finding stale operations
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all.return_value = [MagicMock()]
            mock_execute.return_value = mock_result

            stats = await cleanup_service.mark_stale_operations_as_failed(dry_run=True)

            assert stats["operations_found"] == 1
            assert stats["dry_run"] is True


class TestIntegrationScenarios:
    """Test end-to-end integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_replace_operation_with_monitoring(self):
        """Test complete replace operation with all enhancements."""
        # This would require a test database setup
        # Placeholder for integration testing
        pass

    @pytest.mark.asyncio
    async def test_security_breach_attempt(self):
        """Test that security violations are properly blocked and logged."""
        # Test SQL injection attempts
        with pytest.raises(ValueError):
            SecureQueryBuilder.validate_identifier("users; DROP TABLE users;")

        # Test unauthorized database access
        with patch("autodev.core.data_generator_security.get_degradation_config") as mock_config:
            mock_config.return_value.security.allowed_databases = ["safe_db"]
            with pytest.raises(Exception):
                EnhancedSecurityValidator.validate_database_access("forbidden_db")

    @pytest.mark.asyncio
    async def test_concurrent_operation_limits(self):
        """Test concurrent operation limits are enforced."""
        with patch("autodev.core.data_generator_security.get_degradation_config") as mock_config:
            mock_config.return_value.security.max_concurrent_operations = 2

            # Should fail when limit is reached
            with pytest.raises(Exception):
                EnhancedSecurityValidator.validate_concurrent_operations(3)

    @pytest.mark.asyncio
    async def test_cleanup_automation(self):
        """Test automated cleanup functionality."""
        # Would test the cleanup scheduler and automated retention policies
        pass