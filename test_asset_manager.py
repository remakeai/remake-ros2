#!/usr/bin/env python3
"""
Integration tests for asset manager file operations.

Tests file upload, download, deletion, quota enforcement, and security.
"""

import unittest
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List
import hashlib


@dataclass
class FileMetadata:
    """Metadata for stored file."""
    filename: str
    path: str
    size_bytes: int
    mime_type: str = "application/octet-stream"
    upload_time: str = ""
    hash_sha256: str = ""
    owner_app_id: str = ""


class SimpleAssetManager:
    """Simplified asset manager for testing file operations."""

    def __init__(self, base_path: str, per_app_quota_mb: float = 100.0):
        """
        Args:
            base_path: Root directory for all assets
            per_app_quota_mb: Maximum storage per app in MB
        """
        self.base_path = Path(base_path)
        self.per_app_quota_mb = per_app_quota_mb
        self.max_file_size_mb = min(per_app_quota_mb / 2, 50)  # Max file size
        self.max_file_size_bytes = int(self.max_file_size_mb * 1024 * 1024)

        # Create base directory
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Track files per app
        self._app_usage: Dict[str, int] = {}  # app_id -> bytes used
        self._app_files: Dict[str, List[FileMetadata]] = {}  # app_id -> [files]

    def _get_app_dir(self, app_id: str) -> Path:
        """Get app-specific directory, creating if needed."""
        app_dir = self.base_path / app_id
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir

    def _sanitize_path(self, filename: str) -> str:
        """Prevent path traversal attacks."""
        # Remove any path separators and traverse attempts
        sanitized = filename.replace('\\', '/').replace('..', '')
        sanitized = sanitized.lstrip('/')
        return sanitized

    def _calculate_hash(self, data: bytes) -> str:
        """Calculate SHA256 hash of data."""
        return hashlib.sha256(data).hexdigest()

    def get_app_usage_bytes(self, app_id: str) -> int:
        """Get total storage used by app in bytes."""
        return self._app_usage.get(app_id, 0)

    def get_app_remaining_quota_bytes(self, app_id: str) -> int:
        """Get remaining quota for app in bytes."""
        used = self.get_app_usage_bytes(app_id)
        total_bytes = int(self.per_app_quota_mb * 1024 * 1024)
        return max(0, total_bytes - used)

    def upload_file(self, app_id: str, filename: str, data: bytes) -> Optional[FileMetadata]:
        """
        Upload file for app.

        Args:
            app_id: Application identifier
            filename: Target filename (relative path)
            data: File data bytes

        Returns:
            FileMetadata if successful, None if failed
        """
        # Sanitize path
        filename = self._sanitize_path(filename)

        # Check file size
        if len(data) > self.max_file_size_bytes:
            raise ValueError(f"File exceeds max size of {self.max_file_size_mb}MB")

        # Check quota
        remaining = self.get_app_remaining_quota_bytes(app_id)
        if len(data) > remaining:
            raise ValueError(
                f"Insufficient quota: need {len(data)} bytes, have {remaining} bytes"
            )

        # Store file
        app_dir = self._get_app_dir(app_id)
        file_path = app_dir / filename

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path.write_bytes(data)

        # Update usage
        self._app_usage[app_id] = self.get_app_usage_bytes(app_id) + len(data)

        # Create metadata
        metadata = FileMetadata(
            filename=filename,
            path=str(file_path),
            size_bytes=len(data),
            mime_type="application/octet-stream",
            hash_sha256=self._calculate_hash(data),
            owner_app_id=app_id
        )

        # Track file
        if app_id not in self._app_files:
            self._app_files[app_id] = []
        self._app_files[app_id].append(metadata)

        return metadata

    def download_file(self, app_id: str, filename: str) -> Optional[bytes]:
        """
        Download file for app.

        Args:
            app_id: Application identifier
            filename: Target filename (relative path)

        Returns:
            File data bytes if successful, None if not found
        """
        # Sanitize path
        filename = self._sanitize_path(filename)

        app_dir = self._get_app_dir(app_id)
        file_path = app_dir / filename

        if not file_path.exists():
            return None

        # Verify file is within app directory (security check)
        try:
            file_path.resolve().relative_to(app_dir.resolve())
        except ValueError:
            # File is outside app directory (attempted breakout)
            return None

        return file_path.read_bytes()

    def delete_file(self, app_id: str, filename: str) -> bool:
        """
        Delete file for app.

        Args:
            app_id: Application identifier
            filename: Target filename (relative path)

        Returns:
            True if deleted, False if not found
        """
        # Sanitize path
        filename = self._sanitize_path(filename)

        app_dir = self._get_app_dir(app_id)
        file_path = app_dir / filename

        if not file_path.exists():
            return False

        # Get file size before deletion
        file_size = file_path.stat().st_size

        # Delete file
        file_path.unlink()

        # Update usage
        self._app_usage[app_id] = max(0, self.get_app_usage_bytes(app_id) - file_size)

        # Remove from metadata
        if app_id in self._app_files:
            self._app_files[app_id] = [
                f for f in self._app_files[app_id] if f.filename != filename
            ]

        return True

    def list_files(self, app_id: str) -> List[FileMetadata]:
        """List all files for app."""
        return self._app_files.get(app_id, [])

    def get_file_metadata(self, app_id: str, filename: str) -> Optional[FileMetadata]:
        """Get metadata for specific file."""
        for metadata in self.list_files(app_id):
            if metadata.filename == filename:
                return metadata
        return None


class TestAssetUpload(unittest.TestCase):
    """Test file upload functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SimpleAssetManager(self.temp_dir, per_app_quota_mb=10.0)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_upload_simple_file(self):
        """Test uploading a simple file."""
        app_id = "test-app-001"
        filename = "config.json"
        data = b'{"version": "1.0"}'

        metadata = self.manager.upload_file(app_id, filename, data)

        assert metadata is not None
        assert metadata.filename == filename
        assert metadata.size_bytes == len(data)
        assert metadata.owner_app_id == app_id

    def test_upload_with_subdirectory(self):
        """Test uploading file with directory structure."""
        app_id = "test-app-001"
        filename = "data/models/model.pkl"
        data = b"binary_model_data"

        metadata = self.manager.upload_file(app_id, filename, data)

        assert metadata is not None
        assert metadata.filename == filename

        # Verify file exists in correct location
        file_path = Path(metadata.path)
        assert file_path.exists()
        assert file_path.read_bytes() == data

    def test_upload_multiple_files(self):
        """Test uploading multiple files for same app."""
        app_id = "test-app-001"

        m1 = self.manager.upload_file(app_id, "file1.txt", b"content1")
        m2 = self.manager.upload_file(app_id, "file2.txt", b"content2")
        m3 = self.manager.upload_file(app_id, "file3.txt", b"content3")

        files = self.manager.list_files(app_id)
        assert len(files) == 3

    def test_upload_exceeds_file_size_limit(self):
        """Test rejection of files exceeding max file size."""
        app_id = "test-app-001"
        # Create data larger than max file size (10MB quota -> max file 5MB)
        oversized_data = b"x" * (51 * 1024 * 1024)

        with self.assertRaises(ValueError) as ctx:
            self.manager.upload_file(app_id, "huge_file.bin", oversized_data)

        assert "exceeds max size" in str(ctx.exception)

    def test_upload_exceeds_quota(self):
        """Test rejection when quota is exceeded."""
        app_id = "test-app-001"
        # Quota is 10MB, upload two files to reach near-quota, then overflow
        # Note: max single file is 5MB, so we upload 4MB + 4MB = 8MB, then overflow
        large_data = b"x" * (4 * 1024 * 1024)  # 4MB file

        m1 = self.manager.upload_file(app_id, "file1.bin", large_data)
        assert m1 is not None

        m2 = self.manager.upload_file(app_id, "file2.bin", large_data)
        assert m2 is not None  # 8MB total, still under 10MB

        # Third upload should fail
        with self.assertRaises(ValueError) as ctx:
            self.manager.upload_file(app_id, "file3.bin", b"x" * (3 * 1024 * 1024))

        assert "Insufficient quota" in str(ctx.exception)

    def test_path_traversal_prevention(self):
        """Test that path traversal attempts are blocked."""
        app_id = "test-app-001"

        # Try to escape app directory
        traversal_path = "../../escaped/file.txt"
        sanitized = self.manager._sanitize_path(traversal_path)

        # Should remove ".." and leading slashes
        assert ".." not in sanitized
        assert not sanitized.startswith("/")

    def test_file_hash_calculation(self):
        """Test SHA256 hash is calculated correctly."""
        app_id = "test-app-001"
        data = b"test data"

        metadata = self.manager.upload_file(app_id, "test.txt", data)

        expected_hash = hashlib.sha256(data).hexdigest()
        assert metadata.hash_sha256 == expected_hash


class TestAssetDownload(unittest.TestCase):
    """Test file download functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SimpleAssetManager(self.temp_dir, per_app_quota_mb=10.0)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_download_uploaded_file(self):
        """Test downloading a previously uploaded file."""
        app_id = "test-app-001"
        filename = "data.txt"
        original_data = b"original content"

        self.manager.upload_file(app_id, filename, original_data)
        downloaded_data = self.manager.download_file(app_id, filename)

        assert downloaded_data == original_data

    def test_download_nonexistent_file(self):
        """Test downloading a file that doesn't exist."""
        app_id = "test-app-001"

        result = self.manager.download_file(app_id, "nonexistent.txt")

        assert result is None

    def test_download_different_app(self):
        """Test that apps can't access each other's files."""
        # App 1 uploads a file
        self.manager.upload_file("app-1", "secret.txt", b"app1 secret")

        # App 2 tries to access it
        result = self.manager.download_file("app-2", "secret.txt")

        assert result is None

    def test_download_with_path_traversal_attempt(self):
        """Test that path traversal in download is blocked."""
        # Upload a real file
        self.manager.upload_file("app-1", "public.txt", b"public data")

        # Try path traversal to access another app's files
        traversal_path = "../app-2/secret.txt"
        result = self.manager.download_file("app-1", traversal_path)

        # Should return None (file not found in app-1 due to sanitization)
        assert result is None


class TestAssetDeletion(unittest.TestCase):
    """Test file deletion functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SimpleAssetManager(self.temp_dir, per_app_quota_mb=10.0)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_delete_uploaded_file(self):
        """Test deleting an uploaded file."""
        app_id = "test-app-001"
        filename = "deleteme.txt"
        data = b"temporary data"

        self.manager.upload_file(app_id, filename, data)
        assert len(self.manager.list_files(app_id)) == 1

        success = self.manager.delete_file(app_id, filename)

        assert success is True
        assert len(self.manager.list_files(app_id)) == 0

    def test_delete_nonexistent_file(self):
        """Test deleting a file that doesn't exist."""
        app_id = "test-app-001"

        success = self.manager.delete_file(app_id, "nonexistent.txt")

        assert success is False

    def test_delete_frees_quota(self):
        """Test that deleting files frees up quota."""
        app_id = "test-app-001"
        data = b"x" * (5 * 1024 * 1024)  # 5MB

        self.manager.upload_file(app_id, "file1.bin", data)
        initial_remaining = self.manager.get_app_remaining_quota_bytes(app_id)

        self.manager.delete_file(app_id, "file1.bin")
        after_delete = self.manager.get_app_remaining_quota_bytes(app_id)

        # After delete, should have more quota available
        assert after_delete > initial_remaining

    def test_delete_multiple_files(self):
        """Test deleting multiple files."""
        app_id = "test-app-001"

        # Upload 3 files
        for i in range(3):
            self.manager.upload_file(app_id, f"file{i}.txt", b"content")

        assert len(self.manager.list_files(app_id)) == 3

        # Delete 2 of them
        self.manager.delete_file(app_id, "file0.txt")
        self.manager.delete_file(app_id, "file1.txt")

        assert len(self.manager.list_files(app_id)) == 1


class TestQuotaManagement(unittest.TestCase):
    """Test quota enforcement and management."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SimpleAssetManager(self.temp_dir, per_app_quota_mb=10.0)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_quota_initialization(self):
        """Test quota starts at maximum."""
        app_id = "test-app-001"
        remaining = self.manager.get_app_remaining_quota_bytes(app_id)

        expected = 10 * 1024 * 1024  # 10MB
        assert remaining == expected

    def test_quota_tracking_after_upload(self):
        """Test quota is tracked after uploads."""
        app_id = "test-app-001"
        initial_quota = self.manager.get_app_remaining_quota_bytes(app_id)

        data = b"x" * (2 * 1024 * 1024)  # 2MB
        self.manager.upload_file(app_id, "file.bin", data)

        remaining = self.manager.get_app_remaining_quota_bytes(app_id)

        assert remaining == initial_quota - len(data)

    def test_multiple_apps_separate_quotas(self):
        """Test that different apps have separate quotas."""
        data = b"x" * (5 * 1024 * 1024)  # 5MB

        self.manager.upload_file("app-1", "file.bin", data)
        self.manager.upload_file("app-2", "file.bin", data)

        remaining_app1 = self.manager.get_app_remaining_quota_bytes("app-1")
        remaining_app2 = self.manager.get_app_remaining_quota_bytes("app-2")

        # Both should have same remaining quota
        assert remaining_app1 == remaining_app2

    def test_usage_calculation(self):
        """Test total usage calculation."""
        app_id = "test-app-001"

        # Upload files totaling 3MB
        self.manager.upload_file(app_id, "file1.bin", b"x" * (1 * 1024 * 1024))
        self.manager.upload_file(app_id, "file2.bin", b"x" * (2 * 1024 * 1024))

        usage = self.manager.get_app_usage_bytes(app_id)

        assert usage == 3 * 1024 * 1024


class TestAssetSecurity(unittest.TestCase):
    """Test security features."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SimpleAssetManager(self.temp_dir, per_app_quota_mb=10.0)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_app_directory_isolation(self):
        """Test that app files are isolated to their directory."""
        # Create files in two different apps
        self.manager.upload_file("app-1", "secret.txt", b"app1 secret")
        self.manager.upload_file("app-2", "secret.txt", b"app2 secret")

        # Verify they're in different locations
        app1_files = self.manager.list_files("app-1")
        app2_files = self.manager.list_files("app-2")

        assert app1_files[0].path != app2_files[0].path

    def test_path_sanitization(self):
        """Test path sanitization removes dangerous patterns."""
        test_cases = [
            ("../../../etc/passwd", "etcpasswd"),
            ("..\\windows\\system32", "windows\\system32"),
            ("./normal/path", "normal/path"),
            ("///leading/slashes", "leading/slashes"),
        ]

        for input_path, expected_contains in test_cases:
            sanitized = self.manager._sanitize_path(input_path)
            assert ".." not in sanitized
            assert not sanitized.startswith("/")

    def test_file_integrity_verification(self):
        """Test file hash verification."""
        app_id = "test-app-001"
        original_data = b"important data"

        metadata = self.manager.upload_file(app_id, "file.txt", original_data)

        # Verify hash matches
        expected_hash = hashlib.sha256(original_data).hexdigest()
        assert metadata.hash_sha256 == expected_hash

        # Download and verify
        downloaded = self.manager.download_file(app_id, "file.txt")
        downloaded_hash = hashlib.sha256(downloaded).hexdigest()
        assert downloaded_hash == metadata.hash_sha256


if __name__ == '__main__':
    unittest.main()
