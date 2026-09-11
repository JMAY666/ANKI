<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { browser } from "$app/environment";

    import AddedGraph from "./AddedGraph.svelte";
    import ButtonsGraph from "./ButtonsGraph.svelte";
    import CalendarGraph from "./CalendarGraph.svelte";
    import CardCounts from "./CardCounts.svelte";
    import DifficultyGraph from "./DifficultyGraph.svelte";
    import EaseGraph from "./EaseGraph.svelte";
    import FutureDue from "./FutureDue.svelte";
    import GraphsPage from "./GraphsPage.svelte";
    import HourGraph from "./HourGraph.svelte";
    import IntervalsGraph from "./IntervalsGraph.svelte";
    import RangeBox from "./RangeBox.svelte";
    import RetrievabilityGraph from "./RetrievabilityGraph.svelte";
    import ReviewsGraph from "./ReviewsGraph.svelte";
    import StabilityGraph from "./StabilityGraph.svelte";
    import TodayStats from "./TodayStats.svelte";
    import TrueRetention from "./TrueRetention.svelte";

    const graphs = [
        TodayStats,
        FutureDue,
        CalendarGraph,
        ReviewsGraph,
        CardCounts,
        IntervalsGraph,
        StabilityGraph,
        EaseGraph,
        DifficultyGraph,
        RetrievabilityGraph,
        TrueRetention,
        HourGraph,
        ButtonsGraph,
        AddedGraph,
    ];
    // The learning workspace owns scope controls; normal statistics keep their
    // established controls and defaults for other clients and add-ons.
    const query = browser
        ? new URLSearchParams(window.location.search)
        : new URLSearchParams();
    const embedded = query.get("learning") === "1";
    const requestedDays = Number(query.get("days"));
    const initialDays =
        embedded && [0, 7, 28, 365].includes(requestedDays) ? requestedDays : 365;
    const initialSearch = embedded
        ? (query.get("scope") ?? "deck:current")
        : "deck:current";
</script>

<GraphsPage
    {graphs}
    {initialSearch}
    {initialDays}
    controller={embedded ? null : RangeBox}
/>
