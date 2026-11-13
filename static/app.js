(function () {
  "use strict";

  var configEl = document.getElementById("app-config");
  var appConfig = configEl ? JSON.parse(configEl.textContent) : {};
  var STATUSES = appConfig.statuses || ["Planned", "In Progress", "Complete"];
  
  var tasks = [];
  var viewMode = "list";

  // DOM Elements
  var form = document.getElementById("task-form");
  var titleInput = document.getElementById("title");
  var descInput = document.getElementById("description");
  var priorityInput = document.getElementById("priority");
  var dueInput = document.getElementById("due-date");
  var formError = document.getElementById("form-error");
  
  var listEl = document.getElementById("task-list");
  var boardEl = document.getElementById("task-board");
  var btnViewList = document.getElementById("btn-view-list");
  var btnViewBoard = document.getElementById("btn-view-board");

  // Sidebar Stats
  var statTotal = document.getElementById("stat-total");
  var statPlanned = document.getElementById("stat-planned");
  var statProgress = document.getElementById("stat-progress");
  var statComplete = document.getElementById("stat-complete");
  var progressFill = document.getElementById("progress-fill");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function api(method, url, body) {
    var options = { method: method, headers: {}, credentials: "same-origin" };
    if (body) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (res) {
      if (res.status === 401) { window.location.href = "/login"; throw new Error("Unauth"); }
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || "Request failed");
        return data;
      });
    });
  }

  function updateStats() {
    var total = tasks.length;
    var planned = tasks.filter(t => t.status === "Planned").length;
    var progress = tasks.filter(t => t.status === "In Progress").length;
    var complete = tasks.filter(t => t.status === "Complete").length;
    
    statTotal.textContent = total;
    statPlanned.textContent = planned;
    statProgress.textContent = progress;
    statComplete.textContent = complete;
    
    var pct = total === 0 ? 0 : Math.round((complete / total) * 100);
    progressFill.style.width = pct + "%";
  }

  function renderTaskCard(task) {
    var item = el("li", "task");
    item.dataset.status = task.status;
    item.dataset.id = task.id;
    
    // Drag & Drop for Board
    item.draggable = true;
    item.addEventListener("dragstart", function(ev) {
      ev.dataTransfer.setData("text/plain", task.id);
      item.style.opacity = "0.5";
    });
    item.addEventListener("dragend", function() {
      item.style.opacity = "1";
    });

    var top = el("div", "task-top");
    top.appendChild(el("h3", "task-title", task.title));
    
    var actions = el("div", "task-actions");
    var delBtn = el("button", "btn-link danger", "Delete");
    delBtn.onclick = function() { deleteTask(task.id); };
    actions.appendChild(delBtn);
    top.appendChild(actions);
    item.appendChild(top);

    if (task.description) item.appendChild(el("p", "task-desc", task.description));

    var meta = el("div", "task-meta");
    meta.appendChild(el("span", "pill pill-" + task.priority.toLowerCase(), task.priority));
    if (task.due_date) meta.appendChild(el("span", null, "Due: " + task.due_date));
    item.appendChild(meta);

    var statusGroup = el("div", "status-control");
    STATUSES.forEach(function(status) {
      var btn = el("button", "status-btn", status);
      btn.setAttribute("aria-pressed", task.status === status);
      if (task.status !== status) {
        btn.onclick = function() { changeStatus(task.id, status); };
      }
      statusGroup.appendChild(btn);
    });
    item.appendChild(statusGroup);
    return item;
  }

  function render() {
    updateStats();
    
    listEl.innerHTML = "";
    tasks.forEach(function(t) { listEl.appendChild(renderTaskCard(t)); });

    ["Planned", "In Progress", "Complete"].forEach(function(status) {
      var colId = "col-" + status.toLowerCase().replace(" ", "-");
      var col = document.getElementById(colId);
      if (col) {
        col.innerHTML = "";
        tasks.filter(function(t) { return t.status === status; }).forEach(function(t) {
          col.appendChild(renderTaskCard(t));
        });
      }
    });
  }

  function changeStatus(id, newStatus) {
    api("PATCH", "/api/tasks/" + id, { status: newStatus }).then(function() {
      var task = tasks.find(function(t) { return t.id === id; });
      if (task) task.status = newStatus;
      render();
    });
  }

  function deleteTask(id) {
    api("DELETE", "/api/tasks/" + id).then(function() {
      tasks = tasks.filter(function(t) { return t.id !== id; });
      render();
    });
  }

  // Form Submit (Add Task)
  form.addEventListener("submit", function(e) {
    e.preventDefault();
    formError.hidden = true;
    
    if (!titleInput.value.trim()) {
      formError.textContent = "Task title is required.";
      formError.hidden = false;
      return;
    }

    var addBtn = document.getElementById("add-btn");
    addBtn.disabled = true;
    addBtn.textContent = "Saving...";

    api("POST", "/api/tasks", {
      title: titleInput.value.trim(),
      description: descInput.value.trim(),
      priority: priorityInput.value,
      due_date: dueInput.value || null
    }).then(function(data) {
      tasks.unshift(data.task); // Add to top of list
      form.reset();
      render();
    }).catch(function(err) {
      formError.textContent = err.message;
      formError.hidden = false;
    }).finally(function() {
      addBtn.disabled = false;
      addBtn.textContent = "+ Add Task";
    });
  });

  // Toggle Views
  btnViewList.onclick = function() {
    btnViewList.classList.add("is-active");
    btnViewBoard.classList.remove("is-active");
    listEl.style.display = "flex";
    boardEl.style.display = "none";
  };

  btnViewBoard.onclick = function() {
    btnViewBoard.classList.add("is-active");
    btnViewList.classList.remove("is-active");
    listEl.style.display = "none";
    boardEl.style.display = "grid";
  };

  // Drag & Drop Board logic
  ["col-planned", "col-in-progress", "col-complete"].forEach(function(colId) {
    var col = document.getElementById(colId);
    if (!col) return;
    
    col.addEventListener("dragover", function(e) {
      e.preventDefault();
      col.classList.add("is-drag-over");
    });
    col.addEventListener("dragleave", function() {
      col.classList.remove("is-drag-over");
    });
    col.addEventListener("drop", function(e) {
      e.preventDefault();
      col.classList.remove("is-drag-over");
      var taskId = parseInt(e.dataTransfer.getData("text/plain"), 10);
      var targetStatus = col.dataset.status;
      var task = tasks.find(t => t.id === taskId);
      if (task && task.status !== targetStatus) {
        changeStatus(taskId, targetStatus);
      }
    });
  });

  // Load Data
  api("GET", "/api/tasks").then(function(data) {
    tasks = data.tasks;
    render();
  });

})();