#include <tiledb/tiledb>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/pytypes.h>
#include <pybind11/stl.h>

#include "common.h"

namespace libtiledbcpp {

using namespace tiledb;
using namespace tiledbpy::common;
namespace py = pybind11;

void init_vfs(py::module &m) {
  py::class_<VFS>(m, "VFS")
      .def(py::init<const Context &>(), py::keep_alive<1, 2>())
      .def(py::init<const Context &, const Config &>(), py::keep_alive<1, 2>())

      .def("ctx", &VFS::context)
      .def("config", &VFS::config)

      .def("create_bucket", &VFS::create_bucket)
      .def("remove_bucket", &VFS::remove_bucket)
      .def("is_bucket", &VFS::is_bucket)
      .def("empty_bucket", &VFS::empty_bucket)
      .def("is_empty_bucket", &VFS::is_empty_bucket)

      .def("create_dir", &VFS::create_dir)
      .def("is_dir", &VFS::is_dir)
      .def("remove_dir", &VFS::remove_dir)
      .def("dir_size", &VFS::dir_size)
      .def("move_dir", &VFS::move_dir)
      .def("copy_dir", &VFS::copy_dir)

      .def("is_file", &VFS::is_file)
      .def("remove_file", &VFS::remove_file)
      .def("file_size", &VFS::file_size)
      .def("move_file", &VFS::move_file)
      .def("copy_file", &VFS::copy_file)

      .def("ls", &VFS::ls)
      .def("touch", &VFS::touch);
}

class FileHandle {
private:
  Context _ctx;
  tiledb_vfs_fh_t *_fh;

public:
  FileHandle(const Context &ctx, const VFS &vfs, std::string uri,
             tiledb_vfs_mode_t mode)
      : _ctx(ctx) {
    _ctx.handle_error(tiledb_vfs_open(_ctx.ptr().get(), vfs.ptr().get(),
                                      uri.c_str(), mode, &this->_fh));
  }

  void close() { tiledb_vfs_close(_ctx.ptr().get(), this->_fh); }

  py::bytes read(uint64_t offset, uint64_t nbytes) {
    py::array data = py::array(py::dtype::of<std::byte>(), nbytes);
    py::buffer_info buffer = data.request();

    _ctx.handle_error(tiledb_vfs_read(_ctx.ptr().get(), this->_fh, offset,
                                      buffer.ptr, nbytes));

    auto np = py::module::import("numpy");
    auto to_bytes = np.attr("ndarray").attr("tobytes");

    return to_bytes(data);
  }

  void write(py::buffer data) {
    py::buffer_info buffer = data.request();
    _ctx.handle_error(tiledb_vfs_write(_ctx.ptr().get(), this->_fh, buffer.ptr,
                                       buffer.shape[0]));
  }

  void flush() {
    _ctx.handle_error(tiledb_vfs_sync(_ctx.ptr().get(), this->_fh));
  }

  bool closed() {
    int32_t is_closed;
    _ctx.handle_error(
        tiledb_vfs_fh_is_closed(_ctx.ptr().get(), this->_fh, &is_closed));
    return is_closed;
  }
};

void init_file_handle(py::module &m) {
  py::class_<FileHandle>(m, "FileHandle")
      .def(py::init<const Context &, const VFS &, std::string,
                    tiledb_vfs_mode_t>(),
           py::keep_alive<1, 2>())

      .def_property_readonly("closed", &FileHandle::closed)

      .def("close", &FileHandle::close)
      .def("read", &FileHandle::read)
      .def("write", &FileHandle::write)
      .def("flush", &FileHandle::flush);
}

} // namespace libtiledbcpp