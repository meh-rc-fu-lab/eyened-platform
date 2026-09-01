<script lang="ts">
    import { goto } from "$app/navigation";
    import Main from "$lib/components/Main.svelte";
    import { fetchApi } from "$lib/api/client";
    import { ArrowLeft, ArrowRight, SkipForward } from "@lucide/svelte";
    import { onMount } from "svelte";

    type SDDRow = {
        row_key: string;
        pdb: string;
        sdb: string;
        bscan: string;
        x_start: number;
        x_end: number;
        width_px: number;
        decision: number | null;
        stage: number | null;
        grader: number | null;
        laterality: "L" | "R" | string | null;
        oct_dcm_path: string;
        oct_dcm_path_updated?: string | null;
        image_url: string | null;
        comment: string | null;
    };

    const decisions = [
        { value: 0, label: "Present" },
        { value: 1, label: "Absent" },
        { value: 2, label: "Uncertain" },
    ];

    let rows = $state<SDDRow[]>([]);
    let currentIndex = $state(0);
    let loading = $state(true);
    let saving = $state(false);
    let error = $state("");
    let dialogOpen = $state(false);
    let selectedStage = $state(1);
    let comment = $state("");
    let imageStates = $state<Record<string, "loading" | "loaded" | "error"> >({});
    let imageDimensions = $state<Record<string, { width: number; height: number }>>({});

    const current = $derived(rows[currentIndex]);
    const sameEyeRows = $derived(rows.filter((row) => row.pdb === current?.pdb && row.sdb === current?.sdb && row.laterality === current?.laterality));
    const sameEyeIndex = $derived(sameEyeRows.findIndex((row) => row.row_key === current?.row_key));
    const previous = $derived(sameEyeIndex > 0 ? sameEyeRows[sameEyeIndex - 1] : undefined);
    const next = $derived(sameEyeIndex >= 0 && sameEyeIndex < sameEyeRows.length - 1 ? sameEyeRows[sameEyeIndex + 1] : undefined);
    const loadedImageCount = $derived(Object.values(imageStates).filter((state) => state === "loaded").length);
    const imageLoadCount = $derived([current, previous, next].filter(Boolean).length);
    const imageProgress = $derived(imageLoadCount === 0 ? 0 : Math.round((loadedImageCount / imageLoadCount) * 100));
    const imagesReady = $derived([previous, current, next].filter(Boolean).every((row) => !row?.image_url || imageStates[row.row_key] === "loaded" || imageStates[row.row_key] === "error"));

    async function loadRows() {
        loading = true;
        error = "";
        try {
            const response = await fetchApi("/sdd/records");
            if (!response.ok) throw new Error(`Failed to load SDD records (${response.status})`);
            const payload = (await response.json()) as { rows: SDDRow[] };
            rows = payload.rows ?? [];
            imageStates = {};
            imageDimensions = {};
        } catch (err) {
            error = err instanceof Error ? err.message : "Failed to load SDD records";
        } finally {
            loading = false;
        }
    }

    function movePrevious() {
        if (currentIndex > 0) currentIndex -= 1;
    }

    function moveNext() {
        if (currentIndex < rows.length - 1) currentIndex += 1;
    }

    function setImageState(rowKey: string | undefined, state: "loading" | "loaded" | "error", width = 0, height = 0) {
        if (!rowKey) return;
        imageStates[rowKey] = state;
        if (width > 0 && height > 0) imageDimensions[rowKey] = { width, height };
        imageStates = { ...imageStates };
        imageDimensions = { ...imageDimensions };
    }

    function skipCurrent() {
        if (currentIndex < rows.length - 1) currentIndex += 1;
    }

    async function saveDecision(decision: number, stage: number | null = null, textComment: string | null = null) {
        if (!current) return;
        saving = true;
        error = "";
        try {
            const response = await fetchApi(`/sdd/records/${encodeURIComponent(current.row_key)}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ decision, stage, comment: textComment }),
            });
            if (!response.ok) throw new Error(`Failed to save SDD decision (${response.status})`);
            current.decision = decision;
            current.stage = stage;
            current.comment = textComment;
            if (currentIndex < rows.length - 1) currentIndex += 1;
        } catch (err) {
            error = err instanceof Error ? err.message : "Failed to save SDD decision";
        } finally {
            saving = false;
        }
    }

    function chooseDecision(value: number) {
        if (value === 0) {
            selectedStage = current?.stage ?? 1;
            comment = current?.comment ?? "";
            dialogOpen = true;
            return;
        }
        saveDecision(value);
    }

    function confirmPresent() {
        dialogOpen = false;
        saveDecision(0, selectedStage, comment.trim() || null);
    }

    function goBack() {
        goto("/tasks");
    }

    onMount(loadRows);
</script>

<svelte:head>
    <title>SDD Grading</title>
</svelte:head>

<Main>
    {#snippet children()}
        <div class="sdd-page">
            <header class="page-header">
                <div>
                    <p class="eyebrow">Task 65</p>
                    <h1>SDD Grading</h1>
                </div>
                {#if rows.length > 0}
                    <span class="counter">{currentIndex + 1} / {rows.length}</span>
                {/if}
            </header>

            {#if loading}
                <p class="state">Loading assigned scans...</p>
            {:else if error}
                <p class="error">{error}</p>
            {:else if rows.length === 0}
                <p class="state">No SDD scans are assigned to you.</p>
            {:else}
                <div class="image-progress" aria-live="polite">
                    Images: {imageProgress}% ({loadedImageCount}/{imageLoadCount})
                </div>
                <section class="viewer" aria-label="SDD scan viewer">
                    <div class="scan side-scan">
                        <span>Previous {previous?.laterality === "L" ? "(Left eye)" : previous?.laterality === "R" ? "(Right eye)" : ""}</span>
                        {#if previous?.image_url}
                            <div class="image-stage">
                                <img src={previous.image_url} alt="Previous OCT scan" loading="lazy" onload={(event) => setImageState(previous?.row_key, "loaded", event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)} onerror={() => setImageState(previous?.row_key, "error")} />
                                {#if imageStates[previous.row_key] !== "loaded" && imageStates[previous.row_key] !== "error"}
                                    <div class="image-loading" role="progressbar" aria-label="Loading previous OCT scan"><div class="svelte-f4erjd"></div></div>
                                {/if}
                                {#if imageStates[previous.row_key] === "error"}<span class="image-error">Unable to load</span>{/if}
                            </div>
                        {:else}
                            <div class="empty-scan">No previous scan</div>
                        {/if}
                    </div>
                    <div class="scan main-scan">
                        <span>Current {current.laterality === "L" ? "(Left eye)" : current.laterality === "R" ? "(Right eye)" : ""}</span>
                        {#if current.image_url}
                            <div class="image-stage" style={`--image-ratio: ${imageDimensions[current.row_key] ? `${imageDimensions[current.row_key].width} / ${imageDimensions[current.row_key].height}` : `${current.width_px} / 1`}`}>
                                <img src={current.image_url} alt="Current OCT scan" onload={(event) => setImageState(current.row_key, "loaded", event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)} onerror={() => setImageState(current.row_key, "error")} />
                                {#if imageStates[current.row_key] !== "loaded" && imageStates[current.row_key] !== "error"}
                                    <div class="image-loading" role="progressbar" aria-label="Loading current OCT scan"><div class="svelte-f4erjd"></div></div>
                                {/if}
                                {#if current.x_start != null && imageDimensions[current.row_key]?.width}<span class="marker" style={`left: ${Math.max(0, Math.min(100, (current.x_start / imageDimensions[current.row_key].width) * 100))}%`} aria-label="Start position"></span>{/if}
                                {#if current.x_end != null && imageDimensions[current.row_key]?.width}<span class="marker" style={`left: ${Math.max(0, Math.min(100, (current.x_end / imageDimensions[current.row_key].width) * 100))}%`} aria-label="End position"></span>{/if}
                                {#if imageStates[current.row_key] === "error"}<span class="image-error">Unable to load</span>{/if}
                            </div>
                        {:else}
                            <div class="empty-scan">Image unavailable</div>
                        {/if}
                        <div class="metadata">{current.pdb} / {current.sdb} / {current.bscan}</div>
                    </div>
                    <div class="scan side-scan">
                        <span>Next</span>
                        {#if next?.image_url}
                            <div class="image-stage">
                                <img src={next.image_url} alt="Next OCT scan" loading="lazy" onload={(event) => setImageState(next?.row_key, "loaded", event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)} onerror={() => setImageState(next?.row_key, "error")} />
                                {#if imageStates[next.row_key] !== "loaded" && imageStates[next.row_key] !== "error"}
                                    <div class="image-loading" role="progressbar" aria-label="Loading next OCT scan"><div class="svelte-f4erjd"></div></div>
                                {/if}
                                {#if imageStates[next.row_key] === "error"}<span class="image-error">Unable to load</span>{/if}
                            </div>
                        {:else}
                            <div class="empty-scan">No next scan</div>
                        {/if}
                    </div>
                </section>

                <div class="actions">
                    <button class="secondary" type="button" onclick={movePrevious} disabled={currentIndex === 0 || saving || !imagesReady}>
                        <ArrowLeft size={16} /> Back
                    </button>
                    {#each decisions as decision}
                        <button
                            class:present={decision.value === 0}
                            class="decision"
                            type="button"
                            onclick={() => chooseDecision(decision.value)}
                            disabled={saving || !imagesReady}
                        >{decision.label}</button>
                    {/each}
                    <button class="secondary" type="button" onclick={skipCurrent} disabled={saving || !imagesReady || currentIndex >= rows.length - 1}>
                        <SkipForward size={16} /> Skip
                    </button>
                </div>
            {/if}
        </div>
    {/snippet}
</Main>

{#if dialogOpen}
    <div class="backdrop" role="presentation" onclick={(event) => event.target === event.currentTarget && (dialogOpen = false)}>
        <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="sdd-dialog-title">
            <h2 id="sdd-dialog-title">SDD Present</h2>
            <fieldset>
                <legend>Stage</legend>
                {#each [1, 2, 3, 4] as stage}
                    <label><input type="radio" name="stage" value={stage} bind:group={selectedStage} /> Stage {stage}</label>
                {/each}
            </fieldset>
            <label class="comment-label" for="sdd-comment">Comment</label>
            <input id="sdd-comment" type="text" bind:value={comment} />
            <div class="dialog-actions">
                <button class="secondary" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
                <button class="primary" type="button" onclick={confirmPresent}>OK</button>
            </div>
        </div>
    </div>
{/if}

<style>
    .sdd-page { width: min(1400px, 100%); margin: 0 auto; padding: 24px; display: grid; gap: 18px; color: #17202a; }
    .page-header { display: flex; align-items: end; justify-content: space-between; border-bottom: 1px solid #dfe5e8; padding-bottom: 12px; }
    .eyebrow { margin: 0 0 4px; color: #64727a; font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    h1 { margin: 0; font-size: 24px; font-weight: 650; }
    .counter { color: #52616b; font-size: 13px; font-variant-numeric: tabular-nums; }
    .viewer { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(360px, 2.4fr) minmax(140px, 1fr); gap: 12px; align-items: stretch; min-height: 430px; }
    .scan { display: grid; grid-template-rows: auto 1fr auto; gap: 8px; min-width: 0; padding: 10px; border: 1px solid #d9e0e4; background: #f5f7f8; }
    .scan > span { color: #64727a; font-size: 11px; font-weight: 700; text-transform: uppercase; }
    .image-progress { color: #52616b; font-size: 12px; text-align: right; }
    .image-stage { position: relative; width: 100%; min-height: 0; height: auto; aspect-ratio: var(--image-ratio, 1); align-self: center; background: #10161a; }
    .scan img { display: block; width: 100%; height: 100%; min-height: 0; object-fit: contain; background: #10161a; }
    .image-loading { position: absolute; inset: 0; display: grid; place-items: center; background: rgb(16 22 26 / 58%); pointer-events: none; }
    .svelte-f4erjd { width: min(72%, 260px); height: 4px; overflow: hidden; background: rgb(255 255 255 / 24%); }
    .svelte-f4erjd::before { content: ""; display: block; width: 40%; height: 100%; background: #5eead4; animation: image-loading 1.1s ease-in-out infinite; }
    @keyframes image-loading { from { transform: translateX(-110%); } to { transform: translateX(275%); } }
    .marker { position: absolute; top: 0; bottom: 0; width: 2px; background: #f97316; box-shadow: 0 0 0 1px rgb(255 255 255 / 60%); pointer-events: none; }
    .image-error { position: absolute; inset: 0; display: grid; place-items: center; color: #fecaca; font-size: 12px; }
    .main-scan { border-color: #91a8b2; background: #eef3f4; }
    .empty-scan { display: grid; place-items: center; min-height: 160px; background: #e8edef; color: #728087; font-size: 12px; text-align: center; }
    .metadata { overflow: hidden; color: #52616b; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
    .actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
    button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; padding: 0 16px; border: 1px solid #aebbc1; border-radius: 4px; background: #fff; color: #17202a; font: inherit; font-size: 13px; cursor: pointer; }
    button:hover:not(:disabled) { border-color: #526d78; background: #f1f5f6; }
    button:disabled { cursor: not-allowed; opacity: .45; }
    .decision { min-width: 100px; }
    .decision.present, .primary { border-color: #176b67; background: #176b67; color: #fff; }
    .secondary { background: #f7f9fa; }
    .state, .error { margin: 24px 0; text-align: center; }
    .error { color: #b42318; }
    .backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgb(13 24 29 / 55%); }
    .dialog { width: min(420px, 100%); display: grid; gap: 16px; padding: 22px; border: 1px solid #cbd5d9; border-radius: 6px; background: #fff; box-shadow: 0 14px 40px rgb(0 0 0 / 22%); }
    .dialog h2 { margin: 0; font-size: 18px; }
    fieldset { display: grid; gap: 10px; margin: 0; padding: 0; border: 0; }
    legend, .comment-label { color: #52616b; font-size: 12px; font-weight: 700; }
    fieldset label { display: flex; align-items: center; gap: 8px; font-size: 13px; }
    .dialog input[type="text"] { width: 100%; box-sizing: border-box; min-height: 38px; padding: 8px 10px; border: 1px solid #aebbc1; border-radius: 4px; font: inherit; }
    .dialog-actions { display: flex; justify-content: end; gap: 8px; }
    @media (max-width: 760px) { .sdd-page { padding: 16px; } .viewer { grid-template-columns: 1fr 1fr; min-height: 300px; } .main-scan { grid-column: 1 / -1; grid-row: 1; min-height: 300px; } .side-scan { min-height: 150px; } }
</style>
