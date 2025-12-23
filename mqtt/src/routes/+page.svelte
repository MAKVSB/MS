<script lang="ts">
  import { onMount } from "svelte";
  import { mqttService } from "$lib/mqttService.svelte";
  import User from "$lib/components/user.svelte";

  let username = $state("");
  let password = $state("");
  let clientId = $state("");
  let textInput = $state("");
  let privateMessageUsername = $state("");

  function send() {
    console.log(textInput.trim())
    if (textInput.trim()) {
      if (privateMessageUsername.trim()){
        mqttService.sendMessage("pm", textInput.trim(), privateMessageUsername.trim());
      } else {
        mqttService.sendMessage("public", textInput, privateMessageUsername);
      }
      textInput = "";
    }
  }

  function signIn() {
    if (mqttService.connected) {
      mqttService.disconnect()
    } else {
      mqttService.connect(username, password, clientId)
    }
  }
</script>

<div class="flex">
  <div class="p-4 max-w-2xl mx-auto">
    <h1 class="text-xl font-bold mb-2">Svelte MQTT Chat</h1>
    <div class="grid gap-2 grid-cols-4">
      <input
        type="text"
        name="username"
        id="username"
        bind:value={username}
        placeholder="Your username"
        class="flex-1 border rounded p-2"
        disabled={mqttService.loggedIn}
      />
      <input
        type="password"
        name="password"
        id="password"
        bind:value={password}
        placeholder="Your password"
        class="flex-1 border rounded p-2"
        disabled={mqttService.loggedIn}
      />
      <input
        type="clientId"
        name="clientId"
        id="clientId"
        bind:value={clientId}
        placeholder="Client id"
        class="flex-1 border rounded p-2"
        disabled={mqttService.loggedIn}
      />
      <button onclick={signIn} class="px-4 py-2 bg-blue-500 text-white rounded">
        {mqttService.loggedIn ? "Logout" : "Login"}
      </button>
      <input
        type="text"
        name="input"
        id="input"
        bind:value={textInput}
        placeholder="Type a message..."
        class="flex-1 border rounded p-2 col-span-4"
        onkeydown={(e) => e.key === "Enter" && send()}
        disabled={!mqttService.loggedIn}
      />
      <input
        type="text"
        name="pm"
        id="pm"
        bind:value={privateMessageUsername}
        placeholder="Private message username"
        class="flex-1 border rounded p-2"
        disabled={!mqttService.loggedIn}
      />
      <button 
      onclick={send}
      class="px-4 py-2 bg-blue-500 text-white rounded  col-span-3"
      disabled={!mqttService.loggedIn}>
        Send
        {#if mqttService.loggedIn}
          (Connected as {mqttService.identity})
          {:else}
          (Disconnected)
        {/if}
      </button>
    </div>
    <div class="border rounded p-2 mt-2 overflow-y-auto bg-gray-50 mb-2 flex flex-col-reverse">
      {#each mqttService.messages as msg}
        {#if privateMessageUsername}
          {#if privateMessageUsername == msg.username || mqttService.identity == msg.username}
            <div class="p-1 border-b text-sm">
              ({msg.time.toUTCString()}) 
              
              {#if msg.private}*{/if}{msg.username}: {msg.message}
            </div>
          {/if}
        {:else}
          <div class="p-1 border-b text-sm">
            ({msg.time.toUTCString()}) 
            
            {#if msg.private}*{/if}{msg.username}: {msg.message}
          </div>
        {/if}
      {/each}
    </div>
  </div>
  <div class="p-4 max-w-sm mx-auto">
    {#if mqttService.loggedIn}
      {#each Object.entries(mqttService.users) as user}
        <div onclick={() => privateMessageUsername = user[0]}>
          <User name={user[0]} online={user[1].connected}></User>
        </div>
      {/each}
    {/if}
  </div>
</div>