//! Conversions between Python objects and core values.

use cassetter_core::protocol::MAX_JSON_DEPTH;
use cassetter_core::CassetteError;
use pyo3::exceptions::{
    PyFileNotFoundError, PyIOError, PyIndexError, PyRecursionError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};

/// Map a core error onto the Python exception the API has always raised.
pub fn to_pyerr(e: CassetteError) -> PyErr {
    match e {
        CassetteError::NotFound(m) => PyFileNotFoundError::new_err(m),
        CassetteError::Io(m) => PyIOError::new_err(m),
        CassetteError::Format(m) | CassetteError::Value(m) => PyValueError::new_err(m),
        CassetteError::IndexOutOfRange(m) => PyIndexError::new_err(m),
    }
}

/// Reject values nested deeper than [`MAX_JSON_DEPTH`].
///
/// `pythonize::depythonize` recurses once per level with no limit of its own,
/// so a deeply nested argument would overflow the Rust stack and abort the
/// interpreter instead of raising.
pub fn check_json_depth(obj: &Bound<'_, PyAny>) -> PyResult<()> {
    let mut stack = vec![(obj.clone(), 0usize)];
    while let Some((item, depth)) = stack.pop() {
        if depth > MAX_JSON_DEPTH {
            return Err(PyRecursionError::new_err(format!(
                "JSON value nested deeper than {MAX_JSON_DEPTH} levels"
            )));
        }
        if let Ok(list) = item.cast::<PyList>() {
            for value in list.iter() {
                stack.push((value, depth + 1));
            }
        } else if let Ok(tuple) = item.cast::<PyTuple>() {
            for value in tuple.iter() {
                stack.push((value, depth + 1));
            }
        } else if let Ok(dict) = item.cast::<PyDict>() {
            for (_, value) in dict.iter() {
                stack.push((value, depth + 1));
            }
        }
    }
    Ok(())
}

/// Depythonize a value after checking its nesting depth.
pub fn depythonize_checked(obj: &Bound<'_, PyAny>) -> PyResult<serde_json::Value> {
    check_json_depth(obj)?;
    Ok(pythonize::depythonize(obj)?)
}
