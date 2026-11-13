(function () {
  "use strict";

  var STATUSES = window.APP_STATUSES || ["Planned", "In Progress", "Complete"];
  var PRIORITIES = window.APP_PRIORITIES || ["Low", "Medium", "High"];
  var LIMITS = window.APP_LIMITS || { title: 100, description: 500 };
  var UNDO_MS = 10000;

  var tasks = [];
  var activeFilter = "All";
  var searchQuery = "";
  var sortKey = "newest";
  var viewMode = localStorage.getItem("task_tracker_view") || "list";
  var editingId = null;
  var focusTarget = null;

  // DOM Elements
  var form = document.getElementById("task-form");
  var titleInput = document.getElementById("title");
  var descInput = document.getElementById("description");
  var priorityInput = document.getElementById("priority");
  var dueInput = document.getElementById("due-date");
  var addBtn = document.getElementById("add-btn");
  var formError = document.getElementById("form-error");

  var listEl = document.getElementById("task-list");
  var boardEl = document.getElementById("task-board");
  var messageEl = document.getElementById("list-message");
  var filtersEl = document.getElementById("filters");
  var searchInput = document.getElementById("search");
  var sortSelect = document.getElementById("sort");
  var toastsEl = document.getElementById("toasts");
  var clearCompletedBtn = document.getElementById("btn-clear-completed");

  var summaryEl = document.getElementById("summary");
  var summaryCountEl = document.getElementById("summary-count");
  var summaryOverdueEl = document.getElementById("summary-overdue");
  var progressEl = document.getElementById("progress");
  var progressFillEl = document.getElementById("progress-fill");

  var statTotalEl = document.getElementById("stat-total");
  var statPlannedEl = document.getElementById("stat-planned");
  var statProgressEl = document.getElementById("stat-progress");
  var statCompleteEl = document.getElementById("stat-complete");
  var statOverdueEl = document.getElementById("stat-overdue");
  var statOverdueCard = document.getElementById("stat-overdue-card");

  var badgePlanned = document.getElementById("badge-planned");
  var badgeInProgress = document.getElementById("badge-in-progress");
  var badgeComplete = document.getElementById("badge-complete");

  var colPlanned = document.getElementById("col-planned");
  var colInProgress = document.getElementById("col-in-progress");
  var colComplete = document.getElementById("col-complete");

  var btnViewList = document.getElementById("btn-view-list");
  var btnViewBoard = document.getElementById("btn-view-board");

  // ---------- Small Helpers ----------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function button(label, className, action) {
    var b = el("button", className, label);
    b.type = "button";
    if (action) { b.dataset.action = action; }
    return b;
  }

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  function todayStr() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function dateOffset(days) {
    var d = new Date();
    d.setDate(d.getDate() + days);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function formatDay(str) {
    if (!str) { return ""; }
    var p = str.split("-");
    if (p.length !== 3) { return str; }
    return new Date(+p[0], +p[1] - 1, +p[2])
      .toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  function formatCreated(iso) {
    if (!iso) { return ""; }
    return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  function isOverdue(task) {
    return task.status !== "Complete" && !!task.due_date && task.due_date < todayStr();
  }

  function truncate(text, max) {
    return text.length > max ? text.slice(0, max - 1) + "…" : text;
  }

  function setMessage(text, isError) {
    if (!messageEl) { return; }
    messageEl.textContent = text || "";
    messageEl.classList.toggle("is-error", !!isError);
  }

  // ---------- API Service ----------
  function api(method, url, body) {
    var options = { method: method, headers: {}, credentials: "same-origin" };
    if (body) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (res) {
      if (res.status === 401) {
        window.location.href = "/login";
        return Promise.reject(new Error("Your session has expired."));
      }
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) { throw new Error(data.error || "Request failed. Please try again."); }
        return data;
      });
    });
  }

  // ---------- Sorting and Filtering ----------
  var PRIORITY_RANK = { High: 0, Medium: 1, Low: 2 };
  var SORTERS = {
    newest: function (a, b) { return b.id - a.id; },
    oldest: function (a, b) { return a.id - b.id; },
    due: function (a, b) {
      if (a.due_date === b.due_date) { return b.id - a.id; }
      if (!a.due_date) { return 1; }
      if (!b.due_date) { return -1; }
      return a.due_date < b.due_date ? -1 : 1;
    },
    priority: function (a, b) {
      return (PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]) || (b.id - a.id);
    }
  };

  function matchesSearch(task) {
    if (!searchQuery) { return true; }
    var q = searchQuery.toLowerCase();
    var content = (task.title + " " + (task.description || "")).toLowerCase();
    return content.indexOf(q) !== -1;
  }

  // ---------- Rendering Metrics & Summary ----------
  function renderMetrics() {
    var total = tasks.length;
    if (summaryEl) { summaryEl.hidden = total === 0; }
    if (!total) {
      if (clearCompletedBtn) { clearCompletedBtn.hidden = true; }
      return;
    }

    var planned = tasks.filter(function (t) { return t.status === "Planned"; }).length;
    var inProgress = tasks.filter(function (t) { return t.status === "In Progress"; }).length;
    var complete = tasks.filter(function (t) { return t.status === "Complete"; }).length;
    var overdue = tasks.filter(isOverdue).length;
    var pct = Math.round((complete / total) * 100);

    if (statTotalEl) { statTotalEl.textContent = total; }
    if (statPlannedEl) { statPlannedEl.textContent = planned; }
    if (statProgressEl) { statProgressEl.textContent = inProgress; }
    if (statCompleteEl) { statCompleteEl.textContent = complete; }

    if (statOverdueCard && statOverdueEl) {
      if (overdue > 0) {
        statOverdueCard.hidden = false;
        statOverdueEl.textContent = overdue;
      } else {
        statOverdueCard.hidden = true;
      }
    }

    if (badgePlanned) { badgePlanned.textContent = planned; }
    if (badgeInProgress) { badgeInProgress.textContent = inProgress; }
    if (badgeComplete) { badgeComplete.textContent = complete; }

    if (summaryCountEl) {
      summaryCountEl.textContent = complete + " of " + total + (total === 1 ? " task" : " tasks") + " complete (" + pct + "%)";
    }
    if (summaryOverdueEl) {
      summaryOverdueEl.textContent = overdue > 0 ? "⚠️ " + overdue + " overdue" : "";
    }
    if (progressFillEl) {
      progressFillEl.style.width = pct + "%";
    }
    if (progressEl) {
      progressEl.setAttribute("aria-valuenow", String(pct));
    }

    if (clearCompletedBtn) {
      clearCompletedBtn.hidden = complete === 0;
    }
  }

  function renderFilters() {
    if (!filtersEl) { return; }
    filtersEl.textContent = "";
    ["All"].concat(STATUSES).forEach(function (name) {
      var count = name === "All" ? tasks.length : tasks.filter(function (t) { return t.status === name; }).length;
      var btn = button(name + " (" + count + ")", "filter");
      btn.setAttribute("aria-pressed", String(name === activeFilter));
      btn.addEventListener("click", function () {
        activeFilter = name;
        render();
      });
      filtersEl.appendChild(btn);
    });
  }

  function dueLabel(task) {
    if (!task.due_date) { return null; }
    if (task.status !== "Complete") {
      if (task.due_date < todayStr()) {
        return { text: "⚠️ Overdue (" + formatDay(task.due_date) + ")", cls: "due is-overdue" };
      }
      if (task.due_date === todayStr()) {
        return { text: "⏳ Due today", cls: "due is-today" };
      }
    }
    return { text: "📅 Due " + formatDay(task.due_date), cls: "due" };
  }

  // ---------- Render Individual Task ----------
  function renderTaskCard(task, isBoardItem) {
    if (task.id === editingId) { return renderEditForm(task); }

    var item = el(isBoardItem ? "div" : "li", "task");
    item.dataset.status = task.status;
    item.dataset.task = task.id;

    if (isBoardItem) {
      item.draggable = true;
      item.addEventListener("dragstart", function (ev) {
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(task.id));
        item.classList.add("is-dragging");
      });
      item.addEventListener("dragend", function () {
        item.classList.remove("is-dragging");
      });
    }

    var top = el("div", "task-top");
    top.appendChild(el("h3", "task-title", task.title));
    var actions = el("div", "task-actions");
    var editBtn = button("Edit", "btn-link", "edit");
    editBtn.setAttribute("aria-label", "Edit task: " + task.title);
    editBtn.addEventListener("click", function () { startEdit(task); });
    var delBtn = button("Delete", "btn-link danger", "delete");
    delBtn.setAttribute("aria-label", "Delete task: " + task.title);
    delBtn.addEventListener("click", function () { deleteTask(task); });
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    top.appendChild(actions);
    item.appendChild(top);

    if (task.description) {
      item.appendChild(el("p", "task-desc", task.description));
    }

    var meta = el("div", "task-meta");
    meta.appendChild(el("span", "pill pill-" + task.priority.toLowerCase(), task.priority + " priority"));
    var due = dueLabel(task);
    if (due) { meta.appendChild(el("span", due.cls, due.text)); }
    meta.appendChild(el("span", "task-date", "Added " + formatCreated(task.created_at)));
    item.appendChild(meta);

    var foot = el("div", "task-foot");
    var group = el("div", "status-control");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Status of " + task.title);
    STATUSES.forEach(function (status) {
      var btn = button(status, "status-btn");
      btn.dataset.value = status;
      btn.setAttribute("aria-pressed", String(task.status === status));
      if (task.status !== status) {
        btn.addEventListener("click", function () { changeStatus(task, status, group); });
      }
      group.appendChild(btn);
    });
    foot.appendChild(group);
    item.appendChild(foot);
    return item;
  }

  function addFormField(parent, labelText, control, id, optional) {
    var wrap = el("div", "field");
    var label = el("label", null, labelText);
    label.htmlFor = id;
    if (optional) {
      label.appendChild(document.createTextNode(" "));
      label.appendChild(el("span", "optional", "(optional)"));
    }
    control.id = id;
    wrap.appendChild(label);
    wrap.appendChild(control);
    parent.appendChild(wrap);
    return wrap;
  }

  function renderEditForm(task) {
    var li = el("li", "task task-editing");
    li.dataset.status = task.status;
    li.dataset.task = task.id;

    var f = el("form", "edit-form");
    f.noValidate = true;
    var key = "edit-" + task.id;

    var title = el("input");
    title.type = "text";
    title.maxLength = LIMITS.title;
    title.value = task.title;
    title.dataset.action = "title";
    addFormField(f, "Title", title, key + "-title");

    var desc = el("textarea");
    desc.rows = 2;
    desc.maxLength = LIMITS.description;
    desc.value = task.description || "";
    addFormField(f, "Description", desc, key + "-desc", true);

    var row = el("div", "field-row");
    var priority = el("select");
    PRIORITIES.forEach(function (p) {
      var opt = el("option", null, p);
      opt.value = p;
      priority.appendChild(opt);
    });
    priority.value = task.priority;
    addFormField(row, "Priority", priority, key + "-priority");

    var due = el("input");
    due.type = "date";
    due.value = task.due_date || "";
    addFormField(row, "Due date", due, key + "-due", true);
    f.appendChild(row);

    var actions = el("div", "form-row");
    var error = el("p", "field-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    var cancel = button("Cancel", "btn btn-secondary");
    var save = el("button", "btn btn-primary", "Save changes");
    save.type = "submit";
    var buttons = el("div", "form-buttons");
    buttons.appendChild(cancel);
    buttons.appendChild(save);
    actions.appendChild(error);
    actions.appendChild(buttons);
    f.appendChild(actions);

    function cancelEdit() {
      editingId = null;
      focusTarget = { id: task.id, action: "edit" };
      render();
    }
    cancel.addEventListener("click", cancelEdit);
    f.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { cancelEdit(); }
    });

    f.addEventListener("submit", function (e) {
      e.preventDefault();
      error.hidden = true;
      if (!title.value.trim()) {
        error.textContent = "Enter a task title.";
        error.hidden = false;
        title.focus();
        return;
      }
      save.disabled = true;
      api("PATCH", "/api/tasks/" + task.id, {
        title: title.value.trim(),
        description: desc.value.trim(),
        priority: priority.value,
        due_date: due.value || null
      }).then(function (data) {
        Object.keys(data.task).forEach(function (k) { task[k] = data.task[k]; });
        editingId = null;
        focusTarget = { id: task.id, action: "edit" };
        render();
      }).catch(function (err) {
        error.textContent = err.message;
        error.hidden = false;
        save.disabled = false;
      });
    });

    li.appendChild(f);
    return li;
  }

  // ---------- Main Render Loop ----------
  function render() {
    renderMetrics();
    renderFilters();

    var sorter = SORTERS[sortKey] || SORTERS.newest;
    var visible = tasks.filter(function (t) {
      if (t.id === editingId) { return true; }
      return (activeFilter === "All" || t.status === activeFilter) && matchesSearch(t);
    }).sort(sorter);

    var filteredCountEl = document.getElementById("filtered-count");
    if (filteredCountEl) {
      filteredCountEl.textContent = tasks.length > 0
        ? "(" + visible.length + " shown)"
        : "";
    }

    if (viewMode === "board") {
      if (listEl) { listEl.hidden = true; }
      if (boardEl) { boardEl.hidden = false; }
      if (btnViewList) { btnViewList.classList.remove("is-active"); }
      if (btnViewBoard) { btnViewBoard.classList.add("is-active"); }

      // Clear columns
      if (colPlanned) { colPlanned.textContent = ""; }
      if (colInProgress) { colInProgress.textContent = ""; }
      if (colComplete) { colComplete.textContent = ""; }

      visible.forEach(function (t) {
        var card = renderTaskCard(t, true);
        if (t.status === "Planned" && colPlanned) { colPlanned.appendChild(card); }
        else if (t.status === "In Progress" && colInProgress) { colInProgress.appendChild(card); }
        else if (t.status === "Complete" && colComplete) { colComplete.appendChild(card); }
      });
    } else {
      if (listEl) { listEl.hidden = false; listEl.textContent = ""; }
      if (boardEl) { boardEl.hidden = true; }
      if (btnViewList) { btnViewList.classList.add("is-active"); }
      if (btnViewBoard) { btnViewBoard.classList.remove("is-active"); }

      visible.forEach(function (t) {
        listEl.appendChild(renderTaskCard(t, false));
      });
    }

    if (tasks.length === 0) {
      setMessage("You have no tasks yet. Add your first task above.");
    } else if (visible.length === 0) {
      setMessage(searchQuery
        ? 'No tasks match "' + searchQuery + '".'
        : 'No tasks with the status "' + activeFilter + '".');
    } else {
      setMessage("");
    }

    if (focusTarget) {
      var container = viewMode === "board" ? boardEl : listEl;
      if (container) {
        var target = container.querySelector('[data-task="' + focusTarget.id + '"] [data-action="' + focusTarget.action + '"]');
        if (target) { target.focus(); }
      }
      focusTarget = null;
    }
  }

  // ---------- Actions ----------
  function startEdit(task) {
    editingId = task.id;
    focusTarget = { id: task.id, action: "title" };
    render();
  }

  function changeStatus(task, newStatus, groupEl) {
    if (task.status === newStatus) { return; }
    if (groupEl) { groupEl.setAttribute("aria-busy", "true"); }

    api("PATCH", "/api/tasks/" + task.id, { status: newStatus })
      .then(function (data) {
        task.status = data.task.status;
        render();
      })
      .catch(function (err) {
        if (groupEl) { groupEl.removeAttribute("aria-busy"); }
        setMessage("Could not update the task status. " + err.message, true);
      });
  }

  function deleteTask(task) {
    api("DELETE", "/api/tasks/" + task.id)
      .then(function () {
        tasks = tasks.filter(function (t) { return t.id !== task.id; });
        if (editingId === task.id) { editingId = null; }
        render();
        showUndoSingle(task);
      })
      .catch(function (err) {
        setMessage("Could not delete the task. " + err.message, true);
      });
  }

  function showUndoSingle(task) {
    var toast = el("div", "toast");
    toast.appendChild(el("span", null, 'Deleted "' + truncate(task.title, 36) + '".'));
    var undo = button("Undo", "toast-btn");
    toast.appendChild(undo);
    toastsEl.appendChild(toast);

    var timer = setTimeout(dismiss, UNDO_MS);
    function dismiss() {
      clearTimeout(timer);
      if (toast.parentNode) { toast.parentNode.removeChild(toast); }
    }

    undo.addEventListener("click", function () {
      undo.disabled = true;
      api("POST", "/api/tasks/" + task.id + "/restore")
        .then(function (data) {
          tasks.push(data.task);
          dismiss();
          render();
        })
        .catch(function (err) {
          undo.disabled = false;
          setMessage("Could not restore task. " + err.message, true);
        });
    });
    undo.focus();
  }

  function clearCompletedTasks() {
    api("POST", "/api/tasks/clear-completed")
      .then(function (data) {
        if (!data.task_ids || data.task_ids.length === 0) { return; }
        var clearedIds = new Set(data.task_ids);
        var removed = tasks.filter(function (t) { return clearedIds.has(t.id); });
        tasks = tasks.filter(function (t) { return !clearedIds.has(t.id); });
        render();
        showUndoMultiple(data.task_ids, removed);
      })
      .catch(function (err) {
        setMessage("Could not clear completed tasks. " + err.message, true);
      });
  }

  function showUndoMultiple(taskIds, removedTasks) {
    var toast = el("div", "toast");
    toast.appendChild(el("span", null, "Cleared " + taskIds.length + " completed task(s)."));
    var undo = button("Undo", "toast-btn");
    toast.appendChild(undo);
    toastsEl.appendChild(toast);

    var timer = setTimeout(dismiss, UNDO_MS);
    function dismiss() {
      clearTimeout(timer);
      if (toast.parentNode) { toast.parentNode.removeChild(toast); }
    }

    undo.addEventListener("click", function () {
      undo.disabled = true;
      api("POST", "/api/tasks/restore-multiple", { task_ids: taskIds })
        .then(function () {
          removedTasks.forEach(function (t) { tasks.push(t); });
          dismiss();
          render();
        })
        .catch(function (err) {
          undo.disabled = false;
          setMessage("Could not restore tasks. " + err.message, true);
        });
    });
    undo.focus();
  }

  // ---------- Drag and Drop for Kanban Board ----------
  [colPlanned, colInProgress, colComplete].forEach(function (col) {
    if (!col) { return; }
    col.addEventListener("dragover", function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      col.classList.add("is-drag-over");
    });
    col.addEventListener("dragleave", function () {
      col.classList.remove("is-drag-over");
    });
    col.addEventListener("drop", function (e) {
      e.preventDefault();
      col.classList.remove("is-drag-over");
      var idStr = e.dataTransfer.getData("text/plain");
      if (!idStr) { return; }
      var taskId = parseInt(idStr, 10);
      var targetStatus = col.dataset.status;
      var targetTask = tasks.find(function (t) { return t.id === taskId; });
      if (targetTask && targetTask.status !== targetStatus) {
        changeStatus(targetTask, targetStatus);
      }
    });
  });

  // ---------- Form Submission ----------
  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (formError) { formError.hidden = true; }

      var title = titleInput.value.trim();
      if (!title) {
        if (formError) {
          formError.textContent = "Enter a task title.";
          formError.hidden = false;
        }
        titleInput.focus();
        return;
      }

      if (addBtn) { addBtn.disabled = true; }
      api("POST", "/api/tasks", {
        title: title,
        description: descInput.value.trim(),
        priority: priorityInput.value,
        due_date: dueInput.value || null
      })
        .then(function (data) {
          tasks.push(data.task);
          form.reset();
          activeFilter = "All";
          searchQuery = "";
          if (searchInput) { searchInput.value = ""; }
          render();
          titleInput.focus();
        })
        .catch(function (err) {
          if (formError) {
            formError.textContent = err.message;
            formError.hidden = false;
          }
        })
        .then(function () {
          if (addBtn) { addBtn.disabled = false; }
        });
    });
  }

  // ---------- Due Date Quick Shortcuts ----------
  document.querySelectorAll(".btn-chip[data-offset]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var offset = parseInt(chip.dataset.offset, 10);
      if (dueInput) { dueInput.value = dateOffset(offset); }
    });
  });

  var clearDateBtn = document.getElementById("btn-clear-date");
  if (clearDateBtn) {
    clearDateBtn.addEventListener("click", function () {
      if (dueInput) { dueInput.value = ""; }
    });
  }

  // ---------- View Mode Toggles ----------
  if (btnViewList) {
    btnViewList.addEventListener("click", function () {
      viewMode = "list";
      localStorage.setItem("task_tracker_view", "list");
      render();
    });
  }
  if (btnViewBoard) {
    btnViewBoard.addEventListener("click", function () {
      viewMode = "board";
      localStorage.setItem("task_tracker_view", "board");
      render();
    });
  }

  // ---------- Search & Sort Handlers ----------
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      searchQuery = searchInput.value.trim();
      render();
    });
  }

  if (sortSelect) {
    sortSelect.addEventListener("change", function () {
      sortKey = sortSelect.value;
      render();
    });
  }

  if (clearCompletedBtn) {
    clearCompletedBtn.addEventListener("click", clearCompletedTasks);
  }

  // ---------- Initial Load ----------
  setMessage("Loading your tasks…");
  api("GET", "/api/tasks")
    .then(function (data) {
      tasks = data.tasks;
      render();
    })
    .catch(function (err) {
      setMessage("Could not load tasks. " + err.message, true);
    });
})();
