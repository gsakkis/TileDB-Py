import io
from typing import Optional, Type, TYPE_CHECKING, Union
from types import TracebackType
import warnings

import tiledb.cc as lt
from .ctx import default_ctx

if TYPE_CHECKING:
    from .libtiledb import Ctx, Config


class VFS(lt.VFS):
    """TileDB VFS class

    Encapsulates the TileDB VFS module instance with a specific configuration (config).

    :param tiledb.Ctx ctx: The TileDB Context
    :param config: Override `ctx` VFS configurations with updated values in config.
    :type config: tiledb.Config or dict

    """

    def __init__(self, config: Union["Config", dict] = None, ctx: "Ctx" = None):
        self._ctx = ctx or default_ctx()
        cctx = lt.Context(self._ctx.__capsule__(), False)

        if config:
            from .libtiledb import Config

            if isinstance(config, Config):
                config = config.dict()
            else:
                try:
                    config = dict(config)
                except:
                    raise ValueError("`config` argument must be of type Config or dict")

            ccfg = lt.Config(config)
            super().__init__(cctx, ccfg)
        else:
            super().__init__(cctx)

    def open(self, uri: str, mode: str = "rb"):
        """Opens a VFS file resource for reading / writing / appends at URI

        If the file did not exist upon opening, a new file is created.

        :param str uri: URI of VFS file resource
        :param mode str: 'rb' for opening the file to read, 'wb' to write, 'ab' to append
        :rtype: FileHandle
        :return: TileDB FileIO
        :raises TypeError: cannot convert `uri` to unicode string
        :raises ValueError: invalid mode
        :raises: :py:exc:`tiledb.TileDBError`

        """
        return FileIO(self, uri, mode)

    def close(self, file: lt.FileHandle):
        """Closes a VFS FileHandle object

        :param FileIO file: An opened VFS FileIO
        :rtype: FileIO
        :return: closed VFS FileHandle
        :raises: :py:exc:`tiledb.TileDBError`

        """
        if isinstance(file, FileIO):
            warnings.warn(
                f"`tiledb.VFS().open` now returns a a FileIO object. Use "
                "`FileIO.close`.",
                DeprecationWarning,
            )
        file.close()
        return file

    def write(self, file: lt.FileHandle, buff: Union[str, bytes]):
        """Writes buffer to opened VFS FileHandle

        :param FileHandle file: An opened VFS FileHandle in 'w' mode
        :param buff: a Python object that supports the byte buffer protocol
        :raises TypeError: cannot convert buff to bytes
        :raises: :py:exc:`tiledb.TileDBError`

        """
        if isinstance(file, FileIO):
            warnings.warn(
                f"`tiledb.VFS().open` now returns a a FileIO object. Use "
                "`FileIO.write`.",
                DeprecationWarning,
            )
        if isinstance(buff, str):
            buff = buff.encode()
        file.write(buff)

    def read(self, file: lt.FileHandle, offset: int, nbytes: int):
        """Read nbytes from an opened VFS FileHandle at a given offset

        :param FileHandle file: An opened VFS FileHandle in 'r' mode
        :param int offset: offset position in bytes to read from
        :param int nbytes: number of bytes to read
        :rtype: :py:func:`bytes`
        :return: read bytes
        :raises: :py:exc:`tiledb.TileDBError`

        """
        if isinstance(file, FileIO):
            warnings.warn(
                f"`tiledb.VFS().open` now returns a a FileIO object. Use "
                "`FileIO.seek` and `FileIO.read`.",
                DeprecationWarning,
            )
            return file.read(nbytes)

        if nbytes == 0:
            return b""

        return file.read(offset, nbytes)

    def supports(self, scheme: str) -> bool:
        """Returns true if the given URI scheme (storage backend) is supported

        :param str scheme: scheme component of a VFS resource URI (ex. 'file' / 'hdfs' / 's3')
        :rtype: bool
        :return: True if the linked libtiledb version supports the storage backend, False otherwise
        :raises ValueError: VFS storage backend is not supported

        """
        if scheme == "file":
            return True

        scheme_to_fs_type = {
            "s3": lt.FileSystem.S3,
            "azure": lt.FileSystem.AZURE,
            "gcs": lt.FileSystem.GCS,
            "hdfs": lt.FileSystem.HDFS,
        }

        if scheme not in scheme_to_fs_type:
            raise ValueError(f"Unsupported VFS scheme '{scheme}://'")

        cctx = lt.Context(self._ctx.__capsule__(), False)
        return cctx.is_supported_fs(scheme_to_fs_type[scheme])


class FileIO(io.RawIOBase):
    def __init__(self, vfs: VFS, uri: str, mode: str = "rb"):
        self._vfs = vfs

        str_to_vfs_mode = {
            "rb": lt.VFSMode.READ,
            "wb": lt.VFSMode.WRITE,
            "ab": lt.VFSMode.APPEND,
        }
        if mode not in str_to_vfs_mode:
            raise ValueError(f"invalid mode {mode}")
        self._mode = mode

        self._fh = lt.FileHandle(
            self._vfs.ctx(), self._vfs, uri, str_to_vfs_mode[self._mode]
        )
        self._offset = 0
        self._nbytes = 0

        if self._mode == "rb":
            try:
                self._nbytes = vfs.file_size(uri)
            except:
                raise IOError(f"URI {uri} is not a valid file")

    def __len__(self):
        return self._nbytes

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        self.flush()

    @property
    def mode(self):
        return self._mode

    def readable(self):
        return self._mode == "rb"

    def writable(self):
        return self._mode != "rb"

    @property
    def closed(self):
        return self._fh.closed

    def seekable(self):
        return True

    def flush(self):
        self._fh.flush()

    def seek(self, offset: int, whence: int = 0):
        if not isinstance(offset, int):
            raise TypeError(
                f"Offset must be an integer or None (got {safe_repr(offset)})"
            )
        if whence == 0:
            if offset < 0:
                raise ValueError(
                    "offset must be a positive or zero value when SEEK_SET"
                )
            self._offset = offset
        elif whence == 1:
            self._offset += offset
        elif whence == 2:
            self._offset = self._nbytes + offset
        else:
            raise ValueError("whence must be equal to SEEK_SET, SEEK_START, SEEK_END")
        if self._offset < 0:
            self._offset = 0
        elif self._offset > self._nbytes:
            self._offset = self._nbytes

        return self._offset

    def tell(self):
        return self._offset

    def read(self, size: int = -1):
        if not isinstance(size, int):
            raise TypeError(f"size must be an integer or None (got {safe_repr(size)})")
        if not self.readable():
            raise IOError("Cannot read from write-only FileIO handle")
        if self.closed:
            raise IOError("Cannot read from closed FileIO handle")

        nbytes_left = self._nbytes - self._offset
        nbytes = nbytes_left if size < 0 or size > nbytes_left else size
        if nbytes == 0:
            return b""

        buff = self._fh.read(self._offset, nbytes)
        self._offset += nbytes
        return buff

    def write(self, buff: bytes):
        if not self.writable():
            raise IOError("cannot write to read-only FileIO handle")
        if isinstance(buff, str):
            buff = buff.encode()
        nbytes = len(buff)
        self._fh.write(buff)
        self._nbytes += nbytes
        self._offset += nbytes
        return nbytes