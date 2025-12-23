<script lang="ts">
  let { name, online }: { name: string; online: boolean; } = $props()
</script>
<div
class="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
>
<div class="grid flex-1 text-left text-sm leading-tight border p-2 {online ? "bg-green-500": ""}">
    <span class="truncate font-medium">{name}</span>
</div>
</div>