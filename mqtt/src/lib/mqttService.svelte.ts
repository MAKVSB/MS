// src/lib/mqttService.ts
import pkg from "paho-mqtt";
import { localStore } from "./localstore.svelte";
import { browser } from "$app/environment";

const { Client, Message } = pkg;

interface UserData {
  connected: boolean;
}

interface ReceivedMessage {
  time: Date;
  username: string;
  private: boolean;
  message: string;
}

interface UnsentMessage {
  id: string;
  time: Date;
  sender: string;
  reciever?: string;
  type: "public" | "pm" | "status";
  message: string;
}

class MQTTService {
  private client: pkg.Client | null = null;
  public identity = $state("");
  public messages = $state<ReceivedMessage[]>([]);
  public users = $state<{ [key: string]: UserData }>({});
  public loggedIn = $state(false);
  public connected = $state(false);
  public disconnectedAt = $state(Date.now());
  public unsentMessages = localStore<UnsentMessage[]>("unsent_messages", []);

  constructor() {
    if (browser) {
      setInterval(() => this.sendUnsentMessages(), 10000);
    }
  }

  connect(username: string, password: string, identity: string) {
    const brokerUrl = import.meta.env.VITE_MQTT_BROKER;
    const MQTTusername = username;
    const MQTTpassword = password;

    this.client = new Client(brokerUrl, identity);

    this.client.onConnectionLost = (responseObject: any) => {
      console.error("MQTT connection lost:", responseObject.errorMessage);
    };

    this.client.onMessageArrived = (msg: any) => {
      if (msg.topic.startsWith("/mschat/status/")) {
        const username: string = msg.topic.split("/")[3];
        this.users[username] = {
          connected: msg.payloadString.includes("online"),
        };
      } else {
        const messageParts = msg.payloadString.split(" ");

        const dateString = messageParts[0];
        let message = messageParts.slice(1).join(" ");

        let date = new Date();
        if (new Date(dateString).toUTCString() != "Invalid Date") {
          date = new Date(dateString);
        } else {
          message = dateString + " " + message;
        }

        this.messages.push({
          time: date,
          username: msg.destinationName.split("/").at(-1),
          message: message,
          private: messageParts.length != 4,
        });
      }
    };

    const lwtMessage = new Message(`offline`);
    lwtMessage.destinationName = `/mschat/status/${identity}`;
    lwtMessage.retained = true;
    lwtMessage.qos = 1;

    this.client.connect({
      // Last Will and Testament (sent if client disconnects unexpectedly)
      willMessage: lwtMessage,
      onSuccess: () => {
        this.identity = identity;
        this.client?.subscribe("/mschat/all/#");
        this.client?.subscribe(`/mschat/user/${identity}/#`);
        this.client?.subscribe(`/mschat/status/#`);

        this.loggedIn = true;
        this.connected = true;

        this.sendMessage("status", "online");

        this.sendUnsentMessages();
      },
      onFailure: (err: any) => {
        console.error("MQTT connection failed:", err.errorMessage);
        this.connected = false;
        this.disconnectedAt = Date.now();
      },
      userName: MQTTusername,
      password: MQTTpassword,
      useSSL: brokerUrl.startsWith("wss://"),
      reconnect: true,
      timeout: 5,
      cleanSession: false,
    });

    this.client.onConnectionLost = () => {
      this.connected = false;
      setTimeout(() => {
        for (const [login, userData] of Object.entries(this.users)) {
          this.users[login].connected = false;
        }
      }, 10000);
    };
  }

  disconnect() {
    const lwtMessage = new Message(`offline`);
    lwtMessage.destinationName = `/mschat/status/${this.identity}`;
    lwtMessage.retained = true;
    lwtMessage.qos = 1;

    this.client?.send(lwtMessage);
    this.client?.disconnect();
    this.loggedIn = false;
    this.connected = false;
    this.identity = "";
  }

  sendMessage(
    type: "public" | "pm" | "status",
    text: string,
    recipientId?: string,
    timestamp: number = Date.now()
  ) {
    if (!this.client) return;

    if (!this.sendMessageInternal(type, text, recipientId, timestamp)) {
      this.saveMessage(type, text, recipientId);
    }
  }

  private sendMessageInternal(
    type: "public" | "pm" | "status",
    text: string,
    recipientId?: string,
    timestamp: number = Date.now()
  ): boolean {
    if (!this.client) return false;
    if (!this.connected) {
      return false;
    }

    const ts = Math.floor(timestamp / 1000);
    const payload = type == "status" ? text : `${ts} ${text}`;

    const msg = new Message(payload);
    msg.qos = 1;

    switch (type) {
      case "public":
        msg.destinationName = `/mschat/all/${this.identity}`;
        break;
      case "pm":
        if (!this.users[recipientId!] || !this.users[recipientId!].connected) {
          return false;
        }
        msg.destinationName = `/mschat/user/${recipientId}/${this.identity}`;
        break;
      case "status":
        msg.destinationName = `/mschat/status/${this.identity}`;
        msg.retained = true;
        msg.qos = 1;
        break;
    }
    try {
      this.client.send(msg);
    } catch {
      return false;
    }

    switch (type) {
      case "pm":
        this.messages.push({
          time: new Date(),
          username: this.identity,
          private: true,
          message: text,
        });
    }

    return true;
  }

  private saveMessage(
    type: "public" | "pm" | "status",
    text: string,
    recipientId?: string
  ) {
    if (type == "status") return;

    const unsentMessage: UnsentMessage = {
      id: crypto.randomUUID(),
      time: new Date(),
      sender: this.identity,
      type,
      message: text,
      reciever: recipientId,
    };

    this.unsentMessages.value = [...this.unsentMessages.value, unsentMessage];
  }

  private sendUnsentMessages() {
    const currentIdentityMessages = this.unsentMessages.value.filter(
      (v) => v.sender == this.identity
    );
    const sortedMessages = currentIdentityMessages.sort(
      (a, b) => a.time.getTime() - b.time.getTime()
    );

    for (const message of sortedMessages) {
      this.unsentMessages.value = this.unsentMessages.value.filter(
        (v) => v.id != message.id
      );
      if (
        !this.sendMessageInternal(
          message.type,
          message.message,
          message.reciever,
          message.time.getTime()
        )
      ) {
        this.unsentMessages.value = [...this.unsentMessages.value, message];
      }
    }
  }
}

export const mqttService = new MQTTService();
