// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Some legacy full-card iframes set their pixel height once from innerHeight.
// Keep those viewports fitted without reloading their document, rerunning card
// scripts, or changing saved templates. Smaller embeds and responsive CSS opt out.
export function viewportFrameInset(
    inlineHeight: string,
    top: number,
    width: number,
    viewportWidth: number,
    viewportHeight: number,
): number | null {
    if (!/^\d+(\.\d+)?px$/.test(inlineHeight)) {
        return null;
    }
    const inset = viewportHeight - Number.parseFloat(inlineHeight);
    if (top < -1 || top > 40 || width < viewportWidth - 80 || inset < 0 || inset > 40) {
        return null;
    }
    return inset;
}

export class CardFrameResizer {
    private frames: { element: HTMLIFrameElement; inset: number; height: string }[] = [];
    private pending = false;

    constructor() {
        window.addEventListener("resize", () => {
            if (!this.pending) {
                this.pending = true;
                requestAnimationFrame(() => {
                    this.pending = false;
                    this.resize();
                });
            }
        });
    }

    clear(): void {
        this.frames = [];
    }

    capture(qa: HTMLElement): void {
        this.clear();
        if (document.documentElement.dataset.reviewLayout !== "true") {
            return;
        }
        for (const element of qa.querySelectorAll("iframe")) {
            const rect = element.getBoundingClientRect();
            const inset = viewportFrameInset(
                element.style.height,
                rect.top + window.scrollY,
                rect.width,
                window.innerWidth,
                window.innerHeight,
            );
            if (inset !== null) {
                this.frames.push({ element, inset, height: element.style.height });
            }
        }
    }

    private resize(): void {
        this.frames = this.frames.filter((frame) => {
            // A card may intentionally change its layout later. Respect its update.
            if (!frame.element.isConnected || frame.element.style.height !== frame.height) {
                return false;
            }
            frame.height = `${Math.max(64, window.innerHeight - frame.inset)}px`;
            frame.element.style.height = frame.height;
            return true;
        });
    }
}
