<script lang="ts">
	import Viewer from "$lib/viewer/Viewer.svelte";
	import { instances } from "$lib/data/stores.svelte";
	import { resolveEnfaceOverlaySources } from "$lib/registration/resolveEnfaceOverlaySources";
	import { EnfaceProjectionOverlay } from "$lib/viewer/overlays/EnfaceProjectionOverlay";
	import type { EnfaceProjectionMode } from "$lib/viewer/viewer-utils";
	import { getContext, setContext } from "svelte";
	import type { ViewerWindowContext } from "./viewerWindowContext.svelte";
	import type { AbstractImage } from "$lib/webgl/abstractImage";
	import EnfaceProjectionModeIcon from "./icons/EnfaceProjectionModeIcon.svelte";
	import MainIcon from "./icons/MainIcon.svelte";
	import { OCTLinesOverlay } from "$lib/viewer/overlays/OCTLinesOverlays";
	import Lines from "./icons/Lines.svelte";

	interface Props {
		image: AbstractImage;
	}

	let { image }: Props = $props();

	const viewerWindowContext = getContext<ViewerWindowContext>(
		"viewerWindowContext",
	);

	const viewerContext = viewerWindowContext.topViewers.get(image)!;
	setContext("viewerContext", viewerContext);
	const isProjectionImage = $derived(image.image_id.endsWith("_proj"));
	const resolved = $derived.by(() =>
		resolveEnfaceOverlaySources({
			imageId: image.image_id,
			imageWidth: image.width,
			imageHeight: image.height,
			registration: viewerWindowContext.registration,
			managers: viewerWindowContext.enfaceProjectionManagers,
			getImageSize: (imageId) => {
				for (const [candidate] of viewerWindowContext.topViewers) {
					if (candidate.image_id === imageId) {
						return [candidate.width, candidate.height];
					}
				}
				if (imageId.endsWith("_proj")) {
					const octId = imageId.slice(0, -"_proj".length);
					const manager = viewerWindowContext.enfaceProjectionManagers.get(octId);
					if (manager) return [manager.octImage.width, manager.octImage.depth];
				}
				const metadata = instances.get(imageId);
				return metadata ? [metadata.columns, metadata.rows] : undefined;
			},
			projMode: viewerContext.enfaceProjectionMode,
			linkedModes: viewerContext.enfaceProjectionModesByOct,
		}),
	);
	const paintSources = $derived.by(() =>
		resolved.flatMap((source) => {
			const mainViewerContext = source.manager.mainViewerContext;
			return mainViewerContext ? [{ ...source, mainViewerContext }] : [];
		}),
	);

	// const registration = viewerContext.registration;
	// let linkedImages = $derived(registration.getLinkedImgIds(image.image_id));

	let photoLocators = $derived(
		viewerWindowContext.photoLocators.get(image.image_id)!,
	);
	let hasLocators = $derived(
		image.is2D && photoLocators && photoLocators.length,
	);
	let removeOverlay = () => {};
	let hideOverlay = $state(false);

	$effect(() => {
		removeOverlay();
		if (hasLocators && !hideOverlay) {
			removeOverlay = viewerContext.addOverlay(
				new OCTLinesOverlay(photoLocators),
			);
		} else {
			removeOverlay();
		}
		return removeOverlay;
	});

	$effect(() => {
		const sources = paintSources.filter((source) => source.mode !== "off");
		if (!sources.length) return;
		const overlay = new EnfaceProjectionOverlay(sources, image.webgl);
		const remove = viewerContext.addOverlay(overlay);
		return () => {
			remove();
			overlay.destroy();
		};
	});
	function toggleOverlay(e: MouseEvent) {
		e.stopPropagation();
		hideOverlay = !hideOverlay;
	}

	function cycleProjectionMode(e: MouseEvent) {
		e.stopPropagation();
		const modes: EnfaceProjectionMode[] = ["off", "binary", "heatmap"];
		const index = modes.indexOf(viewerContext.enfaceProjectionMode);
		viewerContext.enfaceProjectionMode = modes[(index + 1) % modes.length];
	}

	function selectImage(e: any) {
		if (e.shiftKey) {
			viewerWindowContext.addImagePanel(image);
		} else {
			viewerWindowContext.setImagePanel(image);
		}
	}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="item" class:wide={image.is3D} onclick={(e) => selectImage(e)}>
	<Viewer showInfo={false} />
	{#if hasLocators || resolved.length > 0}
		<div class="header overlay">
			<div class="content outer">
				<div class="content">
					{#if isProjectionImage && resolved.length > 0}
						<MainIcon
							onclick={cycleProjectionMode}
							active={viewerContext.enfaceProjectionMode !== "off"}
							tooltip="Toggle enface segmentation projection"
						>
							{#snippet iconSnippet()}
								<EnfaceProjectionModeIcon mode={viewerContext.enfaceProjectionMode} />
							{/snippet}
						</MainIcon>
					{/if}
					{#if hasLocators}
						<MainIcon
							onclick={toggleOverlay}
							active={!hideOverlay}
							Icon={Lines}
						/>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	div {
		flex: 1;
		display: flex;
	}
	div.overlay {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		pointer-events: none;
	}
	div.content {
		pointer-events: auto;
		flex: 0;
	}
	div.content.outer {
		flex-direction: column;
	}
	div.item {
		border-bottom: 1px solid gray;
		z-index: 2;
		border-right: 1px solid gray;
		position: relative;
	}
	div.item:hover {
		border-bottom: 1px solid white;
	}
	div.wide {
		flex: 2;
	}
	div.header {
		color: white;
		display: flex;
		margin: 0.5em;
	}
</style>
