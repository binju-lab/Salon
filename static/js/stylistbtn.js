/*  Role D: Ruizhe Zheng 24107708 */
/* 前端响应员工端按钮 */

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

// 员工界面的三个按钮，分别设置预约状态为complete，cancel，noshow
const listScheduleDay = document.querySelector("#daily_schedule");

listScheduleDay.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn || !listScheduleDay.contains(btn)) return;

    const id = Number(btn.dataset.id);
    const action = btn.dataset.action;

    if (action === "complete") completeAppt(id);
    else if (action === "cancel") cancelAppt(id);
    else if (action === "noshow") noshowAppt(id);
});

async function completeAppt(apptId) {
    console.log(`the complete button id:${apptId} is clicked`)
    try {
        const response = await fetch(`/staff/stylist/appointments/${apptId}/complete`, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken,
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            const text = await response.text();
            console.error("backend response body:", text);
            throw new Error("HTTP " + response.status + " body=" + text);
        }
        const data = await response.json();
        const state = document.querySelector(`#state_${apptId}`);
        state.textContent = "state: " + data.state;
    } catch (error) {
        console.error(error);
    }
}

async function cancelAppt(apptId) {
    console.log(`the cancel button id:${apptId} is clicked`)
    try {
        const response = await fetch(`/staff/stylist/appointments/${apptId}/cancel`, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken,
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            const text = await response.text();
            console.error("backend response body:", text);
            throw new Error("HTTP " + response.status + " body=" + text);
        }
        const data = await response.json();
        const state = document.querySelector(`#state_${apptId}`);
        state.textContent = "state: " + data.state;
    } catch (error) {
        console.error(error);
    }
}

async function noshowAppt(apptId) {
    console.log(`the noshow button id:${apptId} is clicked`)
    try {
        const response = await fetch(`/staff/stylist/appointments/${apptId}/noshow`, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken,
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            const text = await response.text();
            console.error("backend response body:", text);
            throw new Error("HTTP " + response.status + " body=" + text);
        }
        const data = await response.json();
        const state = document.querySelector(`#state_${apptId}`);
        state.textContent = "state: " + data.state;
    } catch (error) {
        console.error(error);
    }
}
