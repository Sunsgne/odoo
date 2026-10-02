import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, TextField } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import { call } from "../api";
import { findPage } from "../nav";

const SKIP = new Set(["id", "display_name", "create_uid", "create_date", "write_uid", "write_date", "__last_update"]);
const SHOW = new Set(["char", "text", "selection", "many2one", "boolean", "date", "datetime", "integer", "float", "monetary"]);

function cellValue(value, field) {
  if (value === false || value === null || value === undefined) {
    return "";
  }
  if (field.type === "many2one") {
    return Array.isArray(value) ? value[1] : "";
  }
  if (field.type === "selection") {
    const pair = (field.selection || []).find(([key]) => key === value);
    return pair ? pair[1] : value;
  }
  if (field.type === "boolean") {
    return value ? "是" : "否";
  }
  return value;
}

export function Resource({ setTitle, model: modelProp, domain: domainProp, title, recordId }) {
  const params = useParams();
  const page = findPage(params.key);
  const model = modelProp || (params.model ? decodeURIComponent(params.model) : page?.model);
  const domain = domainProp || page?.domain || [];
  const [fields, setFields] = useState({});
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState({});

  useEffect(() => {
    if (setTitle) {
      setTitle(title || page?.label || model || "");
    }
  }, [model, page, setTitle, title]);

  const columns = useMemo(() => {
    return Object.entries(fields)
      .filter(([name, field]) => field.store !== false && SHOW.has(field.type) && !SKIP.has(name))
      .slice(0, 8)
      .map(([name, field]) => ({
        field: name,
        headerName: field.string || name,
        flex: 1,
        minWidth: 120,
        valueGetter: (value, row) => cellValue(row[name], field),
      }));
  }, [fields]);

  async function load(text = query) {
    if (!model) {
      return;
    }
    const spec = await call(model, "fields_get", [], { attributes: ["string", "type", "selection", "required", "readonly", "store"] });
    setFields(spec);
    let next = domain;
    if (text && spec.name) {
      next = domain.length ? ["&", ...wrap(domain), ["name", "ilike", text]] : [["name", "ilike", text]];
    }
    const names = ["id"].concat(Object.keys(spec).filter((name) => spec[name].store !== false && SHOW.has(spec[name].type) && !SKIP.has(name)).slice(0, 8));
    const found = await call(model, "search_read", [], { domain: next, fields: names, limit: 80, order: "id desc" });
    setRows(found);
  }

  useEffect(() => {
    load("").catch((err) => setError(err.message));
  }, [model, params.key]);

  function openRow(row) {
    const values = {};
    Object.entries(fields).forEach(([name, field]) => {
      if (!SHOW.has(field.type) || SKIP.has(name) || field.store === false) {
        return;
      }
      const value = row[name];
      values[name] = field.type === "many2one" && Array.isArray(value) ? value[0] : value === false ? "" : value;
    });
    setDraft(values);
    setEditing(row.id);
  }

  async function save() {
    const values = {};
    Object.entries(fields).forEach(([name, field]) => {
      if (field.readonly || !SHOW.has(field.type) || SKIP.has(name)) {
        return;
      }
      let value = draft[name];
      if (value === "") {
        value = false;
      }
      if ((field.type === "integer" || field.type === "float" || field.type === "monetary") && value !== false) {
        value = Number(value);
      }
      values[name] = value;
    });
    if (editing === "new") {
      await call(model, "create", [values]);
    } else {
      await call(model, "write", [[editing], values]);
    }
    setEditing(null);
    await load();
  }

  if (!model) {
    return <Alert severity="warning">这个页面还没有对应的数据</Alert>;
  }

  return (
    <Box>
      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      <Box sx={{ display: "flex", gap: 1, mb: 2 }}>
        <TextField size="small" label="查询" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") load().catch((err) => setError(err.message)); }} />
        <Button variant="contained" onClick={() => load().catch((err) => setError(err.message))}>查询</Button>
        <Button variant="outlined" onClick={() => { setEditing("new"); setDraft({}); }}>新建</Button>
      </Box>
      <Box sx={{ height: 640, bgcolor: "background.paper" }}>
        <DataGrid
          rows={rows}
          columns={columns}
          disableRowSelectionOnClick
          onRowClick={(params) => openRow(params.row)}
          pageSizeOptions={[25, 50, 80]}
          initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        />
      </Box>
      <Dialog open={Boolean(editing)} onClose={() => setEditing(null)} fullWidth maxWidth="sm">
        <DialogTitle>{editing === "new" ? "新建" : "编辑"}</DialogTitle>
        <DialogContent sx={{ display: "grid", gap: 2, pt: 1 }}>
          {Object.entries(fields).filter(([name, field]) => SHOW.has(field.type) && !SKIP.has(name) && field.store !== false).slice(0, 16).map(([name, field]) => (
            field.type === "selection" ? (
              <TextField key={name} select label={field.string} value={draft[name] || ""} onChange={(event) => setDraft({ ...draft, [name]: event.target.value })}>
                {(field.selection || []).map(([key, label]) => <MenuItem key={key} value={key}>{label}</MenuItem>)}
              </TextField>
            ) : (
              <TextField
                key={name}
                label={field.string}
                type={field.type === "date" ? "date" : field.type === "integer" || field.type === "float" || field.type === "monetary" ? "number" : "text"}
                value={draft[name] ?? ""}
                onChange={(event) => setDraft({ ...draft, [name]: event.target.value })}
                slotProps={{ inputLabel: { shrink: true } }}
              />
            )
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>关闭</Button>
          <Button variant="contained" onClick={() => save().catch((err) => setError(err.message))}>保存</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function wrap(domain) {
  if (!domain.length) {
    return [];
  }
  if (domain[0] === "&" || domain[0] === "|" || domain[0] === "!") {
    return domain;
  }
  const prefix = Array(Math.max(domain.length - 1, 0)).fill("&");
  return prefix.concat(domain);
}
