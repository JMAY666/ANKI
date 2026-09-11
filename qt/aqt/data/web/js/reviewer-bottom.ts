/* Copyright: Ankitects Pty Ltd and contributors
 * License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html */

/* eslint
@typescript-eslint/no-unused-vars: "off",
*/

let time: number; // set in python code
let timerStopped = false;

let maxTime = 0;

// Width/theme changes can reflow the buttons after Qt's resize event. Measure
// the content once Chromium has laid it out, including the narrow-window row.
let sizeObserver: ResizeObserver | undefined;

function updateTime(): void {
    const timeNode = document.getElementById("time");
    if (maxTime === 0) {
        timeNode.textContent = "";
        return;
    }
    time = Math.min(maxTime, time);
    const m = Math.floor(time / 60);
    const s = time % 60;
    const sStr = String(s).padStart(2, "0");
    const timeString = `${m}:${sStr}`;

    if (maxTime === time) {
        timeNode.innerHTML = `<font color=red>${timeString}</font>`;
    } else {
        timeNode.textContent = timeString;
    }
}

let intervalId: number | undefined;

function showQuestion(txt: string, maxTime_: number): void {
    showAnswer(txt);
    time = 0;
    maxTime = maxTime_;
    updateTime();

    if (intervalId !== undefined) {
        clearInterval(intervalId);
    }

    intervalId = setInterval(function() {
        if (!timerStopped) {
            time += 1;
            updateTime();
        }
    }, 1000);
}

function showAnswer(txt: string, stopTimer = false): void {
    document.getElementById("middle").innerHTML = txt;
    timerStopped = stopTimer;
    if (!sizeObserver) {
        sizeObserver = new ResizeObserver(() => pycmd("reviewBottomSizeChanged"));
        sizeObserver.observe(document.getElementById("outer"));
    }
}

function selectedAnswerButton(): string {
    const node = document.activeElement as HTMLElement;
    if (!node) {
        return;
    }
    return node.dataset.ease;
}
